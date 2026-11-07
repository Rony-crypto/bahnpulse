import duckdb
import pandas as pd
import pytest

from dbp.ask.agent import AskResult, ask, question_language
from dbp.ask.evaluate import check_label, check_number, check_ranking, close
from dbp.ask.sandbox import UnsafeQuery, open_sandbox, run_query


@pytest.fixture(scope="module")
def con():
    return open_sandbox()


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE state_month",
        "SELECT 1; SELECT 2",
        "COPY state_month TO 'out.csv'",
        "ATTACH 'data/bahnpulse.duckdb' AS db",
        "SET enable_external_access = true",
        "SELECT * FROM read_csv('/etc/passwd')",
        "SELECT * FROM duckdb_settings()",
        "SELECT * FROM unknown_table",
    ],
)
def test_sandbox_refuses_anything_but_a_select_on_the_views(con, sql):
    with pytest.raises(UnsafeQuery):
        run_query(con, sql)


def test_sandbox_has_no_file_access_even_without_the_check(con):
    with pytest.raises(duckdb.Error):
        con.sql("SELECT * FROM read_parquet('data/published/marts/agg_state_month_type.parquet')")


def test_sandbox_runs_ctes_and_shows_counts_as_whole_numbers(con):
    result = run_query(
        con,
        "WITH ice AS (SELECT * FROM state_month WHERE train_group = 'ICE') "
        "SELECT sum(arrivals) AS arrivals FROM ice",
    )

    assert str(result.frame["arrivals"].dtype) == "Int64"
    assert not result.truncated


class FakeLLM:
    """Replays prepared replies: SQL plans and answers, in order."""

    last_model = "fake"

    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts = []

    def generate_json(self, prompt, schema):
        self.prompts.append(prompt)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def test_question_the_data_cannot_answer_is_declined(con):
    llm = FakeLLM({"can_answer": False, "sql": "", "reason": "No weather data."})

    result = ask("Will it rain?", con, llm)

    assert result.status == "unanswerable" and result.answer == "No weather data."


def test_failed_sql_is_sent_back_once_with_the_error(con):
    llm = FakeLLM(
        {"can_answer": True, "sql": "SELECT nope FROM state_month", "reason": ""},
        {"can_answer": True, "sql": "SELECT count(*) AS n FROM state_month", "reason": ""},
        {"answer": "There are many rows."},
    )

    result = ask("How many rows?", con, llm)

    assert result.status == "answered" and result.attempts == 2
    assert "Your previous SQL failed" in llm.prompts[1] and "nope" in llm.prompts[1]


def test_unsafe_sql_counts_as_a_failed_attempt(con):
    bad = {"can_answer": True, "sql": "DROP TABLE state_month", "reason": ""}

    result = ask("Delete it", con, FakeLLM(bad, bad))

    assert result.status == "failed" and len(result.errors) == 2


def test_model_outage_is_reported_not_raised(con):
    result = ask("Anything", con, FakeLLM(RuntimeError("Gemini is unavailable right now")))

    assert result.status == "failed" and "unavailable" in result.answer


def answered(frame, answer=""):
    return AskResult(question="q", status="answered", frame=frame, answer=answer)


def test_number_check_allows_rounding_but_not_small_value_drift():
    assert close(53.2, 53.24) and close(53.2, 0.532)
    assert close(0.05, 0.06) and not close(0.05, 0.1)
    reference = pd.DataFrame({"x": [53.2]})
    assert check_number(reference, answered(pd.DataFrame({"group": ["ICE"], "pct": [53.2]})))


def test_label_check_accepts_aliases_and_answer_text():
    reference = pd.DataFrame({"weekday": [7]})
    aliases = {7: ["Sunday", "Sonntag"]}

    assert check_label(reference, answered(pd.DataFrame({"day": ["Sunday"]})), aliases)
    two_rows = pd.DataFrame({"weekday": [1, 7], "pct": [80.0, 90.0]})
    assert check_label(reference, answered(two_rows, "Sunday is best."), aliases)
    assert not check_label(reference, answered(two_rows, "Monday is best."), {})


def test_ranking_check_needs_the_same_order():
    reference = pd.DataFrame({"g": ["S", "RB", "RE"]})

    assert check_ranking(reference, answered(pd.DataFrame({"type": ["S", "RB", "RE"]})))
    assert not check_ranking(reference, answered(pd.DataFrame({"type": ["RB", "S", "RE"]})))


@pytest.mark.parametrize(
    ("question", "language"),
    [
        ("Which state had the best ICE punctuality in August 2026?", "English"),
        ("Welches Bundesland hatte die beste Pünktlichkeit?", "German"),
        ("Wie viele ICE fielen in Hamburg aus?", "German"),
        ("How punctual was München Hbf?", "English"),  # German station, English question
    ],
)
def test_question_language(question, language):
    assert question_language(question) == language

