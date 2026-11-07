"""Floating "Ask AI" chat: questions in English or German, answered with checked SQL.

A round button in the bottom-right corner of every dashboard page opens a chat popover
(CSS: .st-key-bp_chat in theme.py). The pipeline is dbp.ask.agent; this module adds the shared
sandbox, model client and answer cache, and a per-visit question limit. The message list is a
fragment, so asking a question reruns only the chat, not the charts behind it.
"""

from __future__ import annotations

import os
import re

import streamlit as st

from dbp.ask.agent import AskResult, ask
from dbp.ask.llm import KEY_NAMES, PROVIDERS, build_client
from dbp.ask.sandbox import data_period, open_sandbox
from dbp.config import DOCS

# Protects the free API quota of the public app: questions per visitor session.
MAX_QUESTIONS_PER_SESSION = 15
POPOVER = "bp_chat_popover"
EXAMPLES = [
    "Which state had the worst S-Bahn punctuality last month?",
    "Which 5 stations added the most delay minutes?",
    "Wie pünktlich waren ICE-Züge im Vergleich zu RE-Zügen?",
]


def secret(name: str) -> str:
    """A setting from the environment (.env locally) or Streamlit secrets (Cloud)."""
    value = os.getenv(name, "")
    if not value:
        try:
            value = st.secrets.get(name, "")
        except Exception:  # no secrets file at all
            value = ""
    return str(value)


def configured() -> bool:
    return any(secret(provider.key_env) for provider in PROVIDERS.values())


@st.cache_resource(show_spinner=False)
def sandbox():
    return open_sandbox()


@st.cache_resource(show_spinner=False)
def llm():
    # Shared, so every visitor goes through the same rate limiter.
    return build_client(secret)


@st.cache_resource(show_spinner=False)
def answer_cache() -> dict[str, AskResult]:
    return {}


def cached_answer(question: str) -> AskResult:
    """The same question gets the same answer without a second model call. Failures (model
    busy) are not kept, so asking again retries."""
    cache = answer_cache()
    key = " ".join(question.lower().split())
    if key not in cache:
        result = ask(question, sandbox(), llm())
        if result.status == "failed":
            return result
        if len(cache) >= 500:
            cache.pop(next(iter(cache)))
        cache[key] = result
    return cache[key]


def eval_score() -> str:
    """'30 of 32' from the latest docs/ask_eval.md, if it exists."""
    path = DOCS / "ask_eval.md"
    if not path.exists():
        return ""
    match = re.search(r"(\d+) of (\d+) correct", path.read_text(encoding="utf-8"))
    return f"{match.group(1)} of {match.group(2)}" if match else ""


def render_chat() -> None:
    """The floating button and its chat panel. Always shown, so a missing key is explained in
    the panel instead of the button vanishing."""
    with st.container(key="bp_chat"):
        # Keyed and tracked so the close button can set its open state; opening or closing
        # reruns the page.
        with st.popover("Ask AI", icon=":material/chat:", key=POPOVER, on_change="rerun"):
            title, close = st.columns([1, 0.12], vertical_alignment="center")
            title.markdown("**Ask the data**")
            # Outside the chat fragment: closing needs a full rerun to reach the popover.
            close.button(
                "", icon=":material/close:", key="bp_chat_close", type="tertiary",
                help="Close chat", on_click=close_chat,
            )
            if configured():
                chat_panel()
            else:
                st.info(
                    f"The AI chat is not set up yet: it needs an API key ({KEY_NAMES}) in "
                    "the app's secrets."
                )


def close_chat() -> None:
    st.session_state[POPOVER] = False


def set_pending(question: str) -> None:
    st.session_state["bp_chat_pending"] = question


@st.fragment
def chat_panel() -> None:
    history: list[AskResult] = st.session_state.setdefault("ask_history", [])
    left = MAX_QUESTIONS_PER_SESSION - len(history)

    period = data_period(sandbox())
    score = eval_score()
    st.caption(
        f"English or German · {period.first:%b %Y} – {period.last:%b %Y} · answers computed "
        "from the data · no personal information, please"
        + (f" · tested: {score} correct" if score else "")
    )
    messages = st.container(height=360, border=False, key="bp_chat_messages")
    question = st.chat_input(
        "Ask about punctuality, delays…" if left > 0 else "Question limit reached",
        disabled=left <= 0,
        max_chars=300,
        key="bp_chat_input",
    ) or st.session_state.pop("bp_chat_pending", None)

    with messages:
        if not history and not question:
            with st.chat_message("assistant"):
                st.markdown("Hi! Ask me anything about DB punctuality, for example:")
                for number, example in enumerate(EXAMPLES):
                    st.button(
                        example, key=f"bp_chat_example_{number}", on_click=set_pending,
                        args=(example,), width="stretch",
                    )
        # Newest first in the history; a chat reads top to bottom.
        for result in reversed(history):
            render_message(result)
        if question and question.strip() and left > 0:
            with st.chat_message("user"):
                st.markdown(question)
            with st.chat_message("assistant"), st.spinner("Checking the data…"):
                history.insert(0, cached_answer(question.strip()))
            st.rerun(scope="fragment")


def render_message(result: AskResult) -> None:
    with st.chat_message("user"):
        st.markdown(result.question)
    with st.chat_message("assistant"):
        if result.status == "answered":
            st.markdown(result.answer)
        elif result.status == "unanswerable":
            st.markdown(f"The data can't answer this: {result.answer}")
        else:
            st.warning(result.answer)
        if result.sql:
            with st.expander("Query"):
                st.code(result.sql, language="sql")
