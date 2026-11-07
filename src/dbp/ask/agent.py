"""Ask the data: a question in English or German -> checked SQL -> answer from the result.

1. Gemini turns the question into one DuckDB SELECT over the sandbox views, or says the data
   cannot answer it (weather, causes, the future, other countries, ...).
2. The SQL is checked and run in the read-only sandbox (dbp.ask.sandbox).
3. If it fails, the error goes back to Gemini once for a corrected query.
4. Gemini writes a short answer in the question's language using only the result's numbers.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import duckdb
import pandas as pd

from dbp.ask.sandbox import Period, QueryResult, UnsafeQuery, data_period, run_query

STATES = [
    "Baden-Württemberg", "Bayern", "Berlin", "Brandenburg", "Bremen", "Hamburg", "Hessen",
    "Mecklenburg-Vorpommern", "Niedersachsen", "Nordrhein-Westfalen", "Rheinland-Pfalz",
    "Saarland", "Sachsen", "Sachsen-Anhalt", "Schleswig-Holstein", "Thüringen",
]

SCHEMA = f"""
You answer questions about Deutsche Bahn punctuality in Germany with DuckDB SQL.
{{period}}

Tables (all counts are sums you can add up; there are no precomputed percentages):

state_month(federal_state, month, train_group, planned_stops, arrivals, on_time_arrivals,
    cancelled_arrivals, late_minutes, late_6_15, late_16_30, late_31_60, late_over_60)
  One row per federal state, month and train type. arrivals = arrivals that ran with a known
  delay; on_time_arrivals = arrivals under 6 minutes late (DB definition); late_minutes =
  total minutes late (early counts as 0); late_* = arrivals per delay band.
station_month(station_name, federal_state, month, train_group, planned_stops, arrivals,
    on_time_arrivals, cancelled_arrivals, late_minutes)
  The same per station.
state_hour(federal_state, month, train_group, weekday, hour, arrivals, on_time_arrivals)
  By planned arrival hour (0-23) and weekday (1 = Monday ... 7 = Sunday).
delay_sources(month, train_group, ends_late, trips, origin_late_min, running_added_min,
    running_recovered_min, dwell_added_min, dwell_recovered_min, final_late_min)
  Complete trips (first to last station): where their lateness came from. ends_late = the
  trip arrived 6+ min late at its last station. origin = already late at the first station;
  running = added between stations; dwell = added while standing at stations; recovered
  values are negative.
station_delay_gain(station_name, federal_state, month, train_group, measured_stops,
    running_added_min, running_recovered_min, dwell_added_min, dwell_recovered_min,
    delay_starts)
  Delay minutes added at each station: on the way in (running) and while standing (dwell).
  delay_starts = trains that first became 6+ min late there.
delay_along_route(month, train_group, route_pct, stops, late_min, late_stops)
  Lateness by position on the route (route_pct 0 = first station ... 100 = last station).
delay_sources and delay_along_route cover all of Germany: they have no federal_state, because
trips cross state borders. Never present their figures as those of one state; for a state,
use station_delay_gain (stations of that state) or say that the split exists only nationally.

Values:
- train_group: 'ICE', 'IC/EC' (other long-distance), 'RE', 'RB', 'S' (S-Bahn), 'Bus' (rail
  replacement), 'Other'. Long-distance = ICE + IC/EC. Regional = RE + RB. Leave out 'Bus'
  and 'Other' unless asked.
- federal_state (German names): {", ".join(STATES)}.
- station_name as in DB timetables, e.g. 'Hamburg Hbf', 'Frankfurt (Main) Hbf',
  'München Hbf', 'Köln Hbf', 'Berlin Hbf'.

Formulas (always sum first, then divide; never average percentages):
- on-time % = 100.0 * sum(on_time_arrivals) / sum(arrivals)
- cancelled % = 100.0 * sum(cancelled_arrivals) / sum(arrivals + cancelled_arrivals)
- average delay (min) = sum(late_minutes) / sum(arrivals)
- share of late trips' delay from a source = sum(x) / sum(origin_late_min +
  running_added_min + dwell_added_min) for rows with ends_late
- delay added at a station = running_added_min + dwell_added_min; per train = that divided
  by measured_stops

Rules:
- Write one DuckDB SELECT (CTEs allowed) using only these tables. No table functions.
- No month or train type mentioned = all months and all train types except Bus/Other.
- Round percentages and minutes to 1 decimal, but values below 1 to 2 decimals (0.05, not
  0.1 or 0). Give columns clear names.
- Format the SQL over several lines (one clause per line) so people can read it.
- Rankings of stations: only stations with at least 100 arrivals (or 100 measured_stops) in
  the period; return at most 10 rows unless asked.
- Match station names with the exact name when you know it, otherwise ILIKE.
- If the data cannot answer the question (weather, prices, real-time or future trains,
  other countries, anything not in these tables), set can_answer to false and explain
  briefly why.
- The data shows where and when trains were late, never why (no causes such as
  construction, staff, weather or incidents). For a "why" question set can_answer to false
  and say in the reason which related figures the data can show instead.
"""

SQL_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "can_answer": {"type": "BOOLEAN"},
        "sql": {"type": "STRING"},
        "reason": {"type": "STRING"},
    },
    "required": ["can_answer", "sql", "reason"],
}
ANSWER_SCHEMA = {
    "type": "OBJECT",
    "properties": {"answer": {"type": "STRING"}},
    "required": ["answer"],
}


@dataclass
class AskResult:
    question: str
    status: str  # "answered", "unanswerable" or "failed"
    answer: str = ""
    sql: str = ""
    frame: pd.DataFrame | None = None
    truncated: bool = False
    attempts: int = 0
    model: str = ""
    seconds: float = 0.0
    errors: list[str] = field(default_factory=list)


def span(period: Period) -> str:
    """'Nov 2025 - Sep 2026'."""
    return f"{period.first:%b %Y} - {period.last:%b %Y}"


def period_text(period: Period) -> str:
    """The data's months for the SQL prompt, read from the sandbox so it follows new data."""
    text = (
        f"Data: every station and operator, {span(period)} (months as DATE, first of the "
        f"month, e.g. {period.last:%B %Y} = DATE '{period.last:%Y-%m-%d}'; the latest month is "
        f"{period.last:%b %Y})."
    )
    if period.incomplete:
        names = [f"{month:%b %Y}" for month in period.incomplete]
        listed = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
        verb = "is" if len(names) == 1 else "are"
        text += f" {listed} {verb} slightly incomplete (some hours missing)."
    return text


def sql_prompt(question: str, period: Period, failed_sql: str = "", error: str = "") -> str:
    schema = SCHEMA.replace("{period}", period_text(period))
    prompt = f"{schema}\nQuestion: {question}\n"
    if failed_sql:
        prompt += (
            f"\nYour previous SQL failed.\nSQL:\n{failed_sql}\nError: {error}\n"
            "Return a corrected query.\n"
        )
    return prompt


# Common German question words. Umlauts alone do not count: English questions name German
# stations (München Hbf, Köln Hbf).
GERMAN_WORDS = {
    "welche", "welcher", "welches", "wie", "wo", "wann", "warum", "wieviel", "der", "die",
    "das", "und", "im", "bei", "hatte", "hatten", "waren", "war", "ist", "sind", "viele",
    "zwischen", "pünktlich", "pünktlichkeit", "züge", "zug", "ankünfte", "verspätung",
    "verspätet", "bahnhof", "bahnhöfe", "bundesland", "monat", "stunde", "ausgefallen",
}


def question_language(question: str) -> str:
    """'German' when the question uses common German words, else 'English'."""
    words = {word.strip("?.,!:;()\"'").lower() for word in question.split()}
    return "German" if words & GERMAN_WORDS else "English"


def answer_prompt(question: str, sql: str, result: QueryResult, period: Period) -> str:
    rows = result.frame.head(30).to_csv(index=False)
    language = question_language(question)
    separators = "610.635" if language == "German" else "610,635"
    return (
        f"Answer the question in 1-3 full sentences in {language}, using only the numbers in "
        "the result (no outside knowledge, no new calculations beyond simple comparisons). "
        "State the result's key figures with their units, not just a name. Name "
        "the period exactly as the SQL filters it (e.g. August 2026); only if it does not "
        f"filter months, say {span(period)}. Write large numbers with thousands "
        f"separators ({separators}). If the result is empty, say that the data has no "
        "matching rows.\n"
        f"Question: {question}\nSQL:\n{sql}\nResult (CSV"
        f"{', first 30 rows' if len(result.frame) > 30 else ''}):\n{rows}"
    )


def ask(question: str, con: duckdb.DuckDBPyConnection, llm, max_attempts: int = 2) -> AskResult:
    """Answer one question; never raises for model or SQL problems, it reports them."""
    started = time.time()
    result = AskResult(question=question.strip(), status="failed")
    failed_sql, error = "", ""
    period = data_period(con)
    try:
        for attempt in range(1, max_attempts + 1):
            result.attempts = attempt
            plan = llm.generate_json(
                sql_prompt(result.question, period, failed_sql, error), SQL_SCHEMA
            )
            if not plan.get("can_answer"):
                result.status = "unanswerable"
                result.answer = plan.get("reason") or "The data cannot answer this question."
                return result
            result.sql = plan.get("sql", "").strip()
            try:
                query = run_query(con, result.sql)
            except (UnsafeQuery, duckdb.Error) as failure:
                failed_sql, error = result.sql, str(failure).splitlines()[0][:300]
                result.errors.append(error)
                continue
            result.frame, result.truncated = query.frame, query.truncated
            reply = llm.generate_json(
                answer_prompt(result.question, result.sql, query, period), ANSWER_SCHEMA
            )
            result.answer = reply.get("answer", "").strip()
            result.status = "answered"
            return result
        result.answer = "Sorry, I could not build a working query for this question."
        return result
    except RuntimeError as failure:  # model unavailable after retries
        result.errors.append(str(failure))
        result.answer = str(failure)
        return result
    finally:
        result.model = getattr(llm, "last_model", "")
        result.seconds = round(time.time() - started, 1)
