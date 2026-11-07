import json

import pytest

from dbp.ask import llm
from dbp.ask.llm import PROVIDERS, ChatClient, FallbackClient, build_client

SCHEMA = {
    "type": "OBJECT",
    "properties": {"sql": {"type": "STRING"}, "can_answer": {"type": "BOOLEAN"}},
    "required": ["sql", "can_answer"],
}


class FakeResponse:
    def __init__(self, status, body=None, headers=None):
        self.status_code = status
        self.ok = status < 400
        self._body = body or {}
        self.headers = headers or {}
        self.text = json.dumps(self._body)

    def json(self):
        return self._body


def chat_reply(content):
    return FakeResponse(200, {"choices": [{"message": {"content": json.dumps(content)}}]})


@pytest.fixture
def calls(monkeypatch):
    """Queue of fake responses; records requests and sleeps."""
    state = {"responses": [], "requests": [], "sleeps": []}

    def post(url, headers, json, timeout):
        state["requests"].append({"url": url, "headers": headers, "json": json})
        return state["responses"].pop(0)

    monkeypatch.setattr(llm.requests, "post", post)
    monkeypatch.setattr(llm.time, "sleep", lambda seconds: state["sleeps"].append(seconds))
    return state


def test_mistral_request_uses_bearer_key_json_mode_and_lists_the_keys(calls):
    calls["responses"].append(chat_reply({"sql": "SELECT 1", "can_answer": True}))
    client = ChatClient(PROVIDERS["mistral"], "secret")

    reply = client.generate_json("Question?", SCHEMA)

    request = calls["requests"][0]
    assert reply == {"sql": "SELECT 1", "can_answer": True}
    assert request["url"] == "https://api.mistral.ai/v1/chat/completions"
    assert request["headers"]["Authorization"] == "Bearer secret"
    assert request["json"]["response_format"] == {"type": "json_object"}
    assert request["json"]["model"] == "mistral-medium-latest"
    assert "sql (string), can_answer (boolean)" in request["json"]["messages"][0]["content"]


def test_rate_limit_waits_as_long_as_the_provider_asks(calls):
    calls["responses"] += [
        FakeResponse(429, headers={"Retry-After": "7"}),
        chat_reply({"sql": "SELECT 1", "can_answer": True}),
    ]

    ChatClient(PROVIDERS["groq"], "secret").generate_json("Q", SCHEMA)

    assert 7 in calls["sleeps"]


def test_reply_missing_a_key_is_asked_again_then_given_up(calls):
    calls["responses"] += [chat_reply({"sql": "SELECT 1"})] * llm.MAX_ATTEMPTS

    with pytest.raises(RuntimeError, match="unavailable"):
        ChatClient(PROVIDERS["mistral"], "secret").generate_json("Q", SCHEMA)
    assert len(calls["requests"]) == llm.MAX_ATTEMPTS


def test_fallback_uses_the_next_provider_and_names_it(calls):
    calls["responses"] += [FakeResponse(503)] * llm.MAX_ATTEMPTS + [
        chat_reply({"sql": "SELECT 2", "can_answer": True})
    ]
    client = FallbackClient(
        [ChatClient(PROVIDERS["mistral"], "a"), ChatClient(PROVIDERS["groq"], "b")]
    )

    reply = client.generate_json("Q", SCHEMA)

    assert reply["sql"] == "SELECT 2"
    assert client.last_model == "groq/openai/gpt-oss-120b"


def test_refused_request_is_not_retried(calls):
    calls["responses"].append(FakeResponse(401, {"message": "bad key"}))

    with pytest.raises(RuntimeError, match="HTTP 401"):
        ChatClient(PROVIDERS["groq"], "wrong").generate_json("Q", SCHEMA)
    assert len(calls["requests"]) == 1


def test_build_client_keeps_order_skips_missing_keys_and_overrides_first_model():
    settings = {"MISTRAL_API_KEY": "m", "GEMINI_API_KEY": "g", "GEMINI_MODEL": "gemini-x"}

    client = build_client(settings.get, providers="mistral,groq,gemini", model="mistral-large")

    assert [c.label for c in client.clients] == ["mistral/mistral-large", "gemini/gemini-x"]
    with pytest.raises(ValueError):
        build_client({}.get)


def test_groq_adds_its_other_models_before_the_next_provider():
    settings = {"GROQ_API_KEY": "q", "GEMINI_API_KEY": "g"}

    client = build_client(settings.get, providers="groq,gemini")

    assert [c.label for c in client.clients] == [
        "groq/openai/gpt-oss-120b",
        "groq/qwen/qwen3.8-27b",
        "groq/openai/gpt-oss-20b",
        "gemini/gemini-3.5-flash",
    ]


def test_long_rate_limit_moves_on_without_waiting(calls):
    calls["responses"].append(FakeResponse(429, headers={"Retry-After": "413"}))

    with pytest.raises(RuntimeError, match="unavailable"):
        ChatClient(PROVIDERS["groq"], "secret").generate_json("Q", SCHEMA)
    assert len(calls["requests"]) == 1 and 413 not in calls["sleeps"]

