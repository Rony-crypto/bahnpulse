"""Ask the data page: questions in English or German, answered with checked SQL."""

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
EXAMPLES = [
    "Which federal state had the worst S-Bahn punctuality in July 2026?",
    "Which 5 stations added the most delay minutes?",
    "Wie pünktlich waren ICE-Züge im Vergleich zu RE-Zügen?",
    "At which hour are RE trains least punctual?",
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


def set_question(text: str) -> None:
    st.session_state["ask_question"] = text


def render_ask() -> None:
    st.header("Ask the data")
    score = eval_score()
    period = data_period(sandbox())
    st.caption(
        "Ask in English or German about punctuality, cancellations and delays "
        f"({period.first:%b %Y} – {period.last:%b %Y}). An AI model writes a database query, "
        "the data computes the answer, and "
        "the query is shown so you can check it. Questions are sent to an AI service (Groq); "
        "don't enter personal information."
        + (f" Tested on a set of questions with known answers: {score} correct." if score else "")
    )
    if not configured():
        st.info(f"Ask the data needs an AI provider key ({KEY_NAMES}).")
        return

    st.session_state.setdefault("ask_history", [])
    asked = len(st.session_state["ask_history"])
    with st.container(border=True, key="card_ask"):
        example_columns = st.columns(len(EXAMPLES))
        for column, example in zip(example_columns, EXAMPLES, strict=True):
            column.button(
                example, on_click=set_question, args=(example,), width="stretch",
                key=f"example_{EXAMPLES.index(example)}",
            )
        with st.form("ask_form", border=False):
            question = st.text_input(
                "Your question",
                key="ask_question",
                placeholder="e.g. Which station in Hamburg had the most cancelled RE arrivals?",
                max_chars=300,
            )
            submitted = st.form_submit_button(
                "Ask", type="primary", disabled=asked >= MAX_QUESTIONS_PER_SESSION
            )
        if asked >= MAX_QUESTIONS_PER_SESSION:
            st.caption(f"Limit of {MAX_QUESTIONS_PER_SESSION} questions per visit reached.")

    if submitted and question.strip():
        with st.spinner("Writing a query and checking the data…"):
            st.session_state["ask_history"].insert(0, cached_answer(question.strip()))

    history = st.session_state["ask_history"]
    for position, result in enumerate(history):
        # Keyed by order asked, not id(): a repeated question returns the same cached result.
        render_result(result, len(history) - position)


def render_result(result: AskResult, number: int) -> None:
    with st.container(border=True, key=f"card_answer_{number}"):
        st.markdown(f"**{result.question}**")
        if result.status == "answered":
            st.markdown(result.answer)
        elif result.status == "unanswerable":
            st.info(f"The data cannot answer this: {result.answer}")
        else:
            st.warning(result.answer)
        if result.sql:
            with st.expander("How this was answered"):
                st.code(result.sql, language="sql")
                if result.frame is not None:
                    st.dataframe(result.frame, hide_index=True, width="stretch")
                    if result.truncated:
                        st.caption("Showing the first 200 rows.")
                st.caption(
                    f"{result.model} · {result.seconds} s"
                    + (f" · corrected after {result.attempts - 1} failed query"
                       if result.attempts > 1 else "")
                )
