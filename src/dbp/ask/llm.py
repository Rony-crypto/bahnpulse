"""LLM clients for "Ask the data": JSON in, JSON out, with rate limits, retries and fallback.

Providers are tried in order (LLM_PROVIDERS, default "groq,mistral,gemini,gemma"); only those
with an API key take part. Groq's free plan (no card, very fast) is the main one; Mistral's free
plan ($10 of credit a month since August 2026) is optional; Gemini's free tier (20 requests a
day per model) and Gemma (slow, often unstable, same Google key) are the last resorts.

Mistral and Groq share the OpenAI-style chat completions API, so one client serves both;
Gemini has its own REST format. Each client keeps its provider's request rate, waits as long
as a 429 reply asks (Retry-After), retries busy models, dropped connections and malformed
replies, and gives up after a few attempts so the next provider can answer. Temperature 0
keeps answers repeatable for evaluation.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass

import requests

log = logging.getLogger(__name__)

TRANSIENT_STATUS = {429, 500, 502, 503, 504}
# A per-minute limit clears within seconds and is worth waiting for; a longer wait (daily
# allowance used up) means moving on to the next model at once, so visitors never wait minutes.
MAX_ATTEMPTS = 4
MAX_WAIT_SECONDS = 20
# gpt-oss models think before answering; "low" keeps that short (fewer tokens, faster).
REASONING_EFFORT = os.getenv("GROQ_REASONING_EFFORT", "low")


@dataclass(frozen=True)
class Provider:
    name: str
    url: str
    key_env: str
    model_env: str
    default_model: str
    min_interval: float  # seconds between requests (free-plan rate limit)


PROVIDERS = {
    # Free plan: $10 of API credit a month; kept to about 1 request per second.
    "mistral": Provider(
        "mistral",
        "https://api.mistral.ai/v1/chat/completions",
        "MISTRAL_API_KEY",
        "MISTRAL_MODEL",
        "mistral-medium-latest",
        1.1,
    ),
    # Free plan: 30 requests a minute; daily token caps per model.
    "groq": Provider(
        "groq",
        "https://api.groq.com/openai/v1/chat/completions",
        "GROQ_API_KEY",
        "GROQ_MODEL",
        "openai/gpt-oss-120b",
        2.1,
    ),
    # Free tier: 20 requests a day per model (October 2026).
    "gemini": Provider(
        "gemini",
        "https://generativelanguage.googleapis.com/v1beta/models",
        "GEMINI_API_KEY",
        "GEMINI_MODEL",
        "gemini-3.5-flash",
        4.1,
    ),
    # Google's open Gemma on the same key: thousands of free requests a day, but it always
    # thinks first (about 50 s a call), so it is the last resort.
    "gemma": Provider(
        "gemma",
        "https://generativelanguage.googleapis.com/v1beta/models",
        "GEMINI_API_KEY",
        "GEMMA_MODEL",
        "gemma-4-31b-it",
        2.1,
    ),
}
GOOGLE = {"gemini", "gemma"}
# "GROQ_API_KEY, MISTRAL_API_KEY or GEMINI_API_KEY", for messages about a missing key.
_keys = list(dict.fromkeys(p.key_env for p in sorted(PROVIDERS.values(), key=lambda p: p.name != "groq")))
KEY_NAMES = ", ".join(_keys[:-1]) + " or " + _keys[-1]


class TransientError(RuntimeError):
    """Busy model, rate limit, dropped connection or malformed reply: worth retrying."""

    def __init__(self, message: str, wait: float | None = None):
        super().__init__(message)
        self.wait = wait


def json_instruction(schema: dict) -> str:
    """'Reply with only a JSON object with these keys: can_answer (boolean), ...'."""
    keys = ", ".join(
        f"{name} ({spec.get('type', 'string').lower()})"
        for name, spec in schema["properties"].items()
    )
    return f"\n\nReply with only a JSON object with these keys: {keys}."


class ChatClient:
    """One provider and model."""

    def __init__(self, provider: Provider, api_key: str, model: str | None = None):
        if not api_key:
            raise ValueError(f"{provider.key_env} is required.")
        self.provider = provider
        self.api_key = api_key
        self.model = model or provider.default_model
        self.label = f"{provider.name}/{self.model}"
        self._lock = threading.Lock()
        self._last_call = 0.0

    def generate_json(self, prompt: str, schema: dict) -> dict:
        """Return the reply as a dict with the schema's required keys, or raise RuntimeError."""
        error: TransientError | None = None
        for attempt in range(MAX_ATTEMPTS):
            if error is not None:
                time.sleep(min(error.wait or 2 ** (attempt + 1), MAX_WAIT_SECONDS))
            try:
                reply = self._request(prompt + json_instruction(schema), schema)
            except TransientError as failure:
                error = failure
                if failure.wait and failure.wait > MAX_WAIT_SECONDS:
                    break
                continue
            missing = [key for key in schema.get("required", []) if key not in reply]
            if not missing:
                return reply
            error = TransientError(f"reply without {', '.join(missing)}")
        raise RuntimeError(f"{self.label} is unavailable right now ({error}).")

    def _throttle(self) -> None:
        with self._lock:
            wait = self.provider.min_interval - (time.monotonic() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.monotonic()

    def _post(self, prompt: str, schema: dict) -> requests.Response:
        if self.provider.name in GOOGLE:
            return requests.post(
                f"{self.provider.url}/{self.model}:generateContent",
                headers={"x-goog-api-key": self.api_key},
                json={
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "temperature": 0,
                        "responseMimeType": "application/json",
                        "responseSchema": schema,
                    },
                },
                timeout=150,
            )
        body = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": prompt}],
        }
        if "gpt-oss" in self.model and REASONING_EFFORT:
            body["reasoning_effort"] = REASONING_EFFORT
        return requests.post(
            self.provider.url,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=body,
            timeout=90,
        )

    def _request(self, prompt: str, schema: dict) -> dict:
        self._throttle()
        try:
            response = self._post(prompt, schema)
        except (requests.ConnectionError, requests.Timeout) as failure:
            raise TransientError(type(failure).__name__) from failure
        if response.status_code in TRANSIENT_STATUS:
            retry_after = response.headers.get("Retry-After", "")
            wait = float(retry_after) if retry_after.replace(".", "", 1).isdigit() else None
            raise TransientError(f"HTTP {response.status_code}", wait=wait)
        if not response.ok:
            raise RuntimeError(
                f"{self.label} refused the request (HTTP {response.status_code}): "
                f"{response.text[:200]}"
            )
        try:
            body = response.json()
            if self.provider.name in GOOGLE:
                # Skip thought parts (Gemma returns its reasoning before the answer).
                parts = body["candidates"][0]["content"]["parts"]
                text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
            else:
                text = body["choices"][0]["message"]["content"]
            reply = json.loads(text)
        except (KeyError, IndexError, TypeError, ValueError) as failure:
            raise TransientError("malformed reply") from failure
        if not isinstance(reply, dict):
            raise TransientError("reply is not a JSON object")
        return reply


class FallbackClient:
    """Tries each client in order; `last_model` names the one that answered."""

    def __init__(self, clients: list[ChatClient]):
        if not clients:
            raise ValueError(f"No AI provider configured: set {KEY_NAMES}.")
        self.clients = clients
        self.last_model = clients[0].label

    def generate_json(self, prompt: str, schema: dict) -> dict:
        errors = []
        for client in self.clients:
            try:
                reply = client.generate_json(prompt, schema)
            except RuntimeError as failure:
                errors.append(str(failure))
                continue
            self.last_model = client.label
            return reply
        raise RuntimeError("No AI model is available right now: " + " | ".join(errors))


def build_client(
    secret=os.getenv, providers: str | None = None, model: str | None = None
) -> FallbackClient:
    """Clients for every configured provider, in LLM_PROVIDERS order.

    `secret` reads a setting by name (the environment by default, Streamlit secrets on the
    cloud). `model` overrides the first provider's model, for evaluating one model.
    """
    order = providers or secret("LLM_PROVIDERS") or "groq,mistral,gemini,gemma"
    clients = []
    for name in [name.strip() for name in order.split(",") if name.strip()]:
        provider = PROVIDERS.get(name.lower())
        if provider is None:
            # A typo should not take the whole feature down; the other providers still work.
            log.warning("Unknown LLM provider %r in LLM_PROVIDERS; skipped.", name)
            continue
        key = secret(provider.key_env) or ""
        if not key:
            continue
        if model and not clients:
            # Evaluating one model: no extra models of the same provider.
            clients.append(ChatClient(provider, key, model))
            continue
        clients.append(ChatClient(provider, key, secret(provider.model_env) or None))
        if name == "groq":
            # Groq's daily token allowance is per model (one question uses ~4,500 of 200,000),
            # so its other models extend the free capacity before another provider is needed.
            extra = secret("GROQ_FALLBACK_MODELS") or "qwen/qwen3.8-27b,openai/gpt-oss-20b"
            clients += [
                ChatClient(provider, key, extra_model.strip())
                for extra_model in extra.split(",")
                if extra_model.strip() and extra_model.strip() != clients[-1].model
            ]
    return FallbackClient(clients)
