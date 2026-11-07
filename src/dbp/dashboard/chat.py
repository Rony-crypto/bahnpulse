"""Floating "Ask AI" chat: the Ask the data pipeline in a corner popover on the dashboard pages.

It shares the Ask page's answers, history and per-visit question limit (dbp.dashboard.ask).
The panel is a fragment, so asking a question reruns only the chat, not the charts behind it.
"""

from __future__ import annotations

import streamlit as st

from dbp.ask.agent import AskResult
from dbp.ask.llm import KEY_NAMES
from dbp.dashboard.ask import MAX_QUESTIONS_PER_SESSION, cached_answer, configured

EXAMPLES = [
    "Which state had the worst S-Bahn punctuality last month?",
    "Which 5 stations added the most delay minutes?",
    "Wie pünktlich waren ICE-Züge im Vergleich zu RE-Zügen?",
]


def render_chat() -> None:
    """Round button fixed to the bottom-right corner (CSS: .st-key-bp_chat in theme.py).

    Always shown, so a missing key is explained in the panel instead of the button vanishing.
    """
    with st.container(key="bp_chat"):
        with st.popover("Ask AI", icon=":material/chat:"):
            if configured():
                chat_panel()
            else:
                st.markdown("**Ask the data**")
                st.info(
                    f"The AI chat is not set up yet: it needs an API key ({KEY_NAMES}) in "
                    "the app's secrets."
                )


def set_pending(question: str) -> None:
    st.session_state["bp_chat_pending"] = question


@st.fragment
def chat_panel() -> None:
    history: list[AskResult] = st.session_state.setdefault("ask_history", [])
    left = MAX_QUESTIONS_PER_SESSION - len(history)

    st.markdown("**Ask the data**")
    st.caption("English or German. An AI writes a query, the data computes the answer.")
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
        # The Ask page keeps the newest first; a chat reads top to bottom.
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
