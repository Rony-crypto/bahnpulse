"""Score "Ask the data" against the hand-written test set and write docs/ask_eval.md.

Usage:
    uv run python -m dbp.ask.evaluate                                # providers as configured
    uv run python -m dbp.ask.evaluate --provider groq                # one provider only
    uv run python -m dbp.ask.evaluate --provider mistral --model mistral-large-latest

Each question's reference query runs in the same sandbox, and the model's result is compared
with it (see eval_questions.yml for the checks). Numbers match within the rounding of the
reference (0.1 for one decimal); names match exactly, ignoring case.
"""

from __future__ import annotations

import argparse
import math
import time
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import yaml

from dbp.ask.agent import AskResult, ask
from dbp.ask.llm import build_client
from dbp.ask.sandbox import open_sandbox
from dbp.config import DOCS

QUESTIONS = Path(__file__).with_name("eval_questions.yml")


def as_text(value) -> str:
    """Comparable text for a cell: dates as YYYY-MM-DD, whole numbers without decimals."""
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return pd.Timestamp(value).strftime("%Y-%m-%d")
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip().lower()


def numbers_in(row) -> list[float]:
    out = []
    for value in row:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if not math.isnan(number):
            out.append(number)
    return out


def close(expected: float, actual: float) -> bool:
    """Within the reference's rounding, or 0.5% for large counts; also accepts 0-1 shares."""
    # Small values (0.05%) need a tighter band than one-decimal rounding allows.
    tolerance = max(0.15 if abs(expected) >= 1 else 0.02, abs(expected) * 0.005)
    return abs(expected - actual) <= tolerance or abs(expected - 100 * actual) <= tolerance


def check_number(reference: pd.DataFrame, result: AskResult) -> bool:
    expected = numbers_in(reference.iloc[0])[0]
    return any(close(expected, value) for value in numbers_in(result.frame.iloc[0]))


def check_numbers(reference: pd.DataFrame, result: AskResult) -> bool:
    found = [value for _, row in result.frame.iterrows() for value in numbers_in(row)]
    return all(
        any(close(expected, value) for value in found)
        for expected in reference.iloc[:, -1].astype(float)
    )


def check_label(reference: pd.DataFrame, result: AskResult, aliases: dict) -> bool:
    expected = reference.iloc[0, 0]
    names = {as_text(expected)} | {name.lower() for name in aliases.get(expected, [])}
    first_row = {as_text(value) for value in result.frame.iloc[0]}
    if names & first_row:
        return True
    in_result = any(as_text(value) in names for value in result.frame.to_numpy().ravel())
    return in_result and any(name in result.answer.lower() for name in names)


def check_ranking(reference: pd.DataFrame, result: AskResult) -> bool:
    expected = [as_text(value) for value in reference.iloc[:, 0]]
    return any(
        [as_text(value) for value in result.frame[column].head(len(expected))] == expected
        for column in result.frame.columns
    )


def grade(item: dict, result: AskResult, con) -> bool:
    if item["check"] == "decline":
        return result.status == "unanswerable"
    if result.status != "answered" or result.frame is None or result.frame.empty:
        return False
    references = item["reference"]
    references = references if isinstance(references, list) else [references]
    return any(matches(item, con.sql(sql).df(), result) for sql in references)


def matches(item: dict, reference: pd.DataFrame, result: AskResult) -> bool:
    if item["check"] == "number":
        return check_number(reference, result)
    if item["check"] == "numbers":
        return check_numbers(reference, result)
    if item["check"] == "label":
        return check_label(reference, result, item.get("aliases", {}))
    return check_ranking(reference, result)


def is_outage(result: AskResult) -> bool:
    return result.status == "failed" and any("unavailable" in e for e in result.errors)


def describe(result: AskResult) -> str:
    """Short reason for a failed check."""
    if is_outage(result):
        return "model unavailable"
    if result.status == "failed":
        return "no working query: " + (result.errors[-1][:70] if result.errors else "")
    if result.status == "unanswerable":
        return "declined: " + result.answer[:70]
    return "wrong result"


def split_summary(table: pd.DataFrame) -> list[str]:
    """Tuning questions shaped the prompt; hold-out questions were written afterwards and
    never used to change it, so their score is the fair one."""
    holdout = table["id"].str.startswith("holdout")
    lines = []
    for name, part in (("Tuning set", table[~holdout]), ("Hold-out set", table[holdout])):
        if len(part):
            outages = int((part["note"] == "model unavailable").sum())
            lines.append(
                f"- **{name}:** {int(part['passed'].sum())} of {len(part)} correct"
                + (f" ({outages} not answered: model unavailable)" if outages else "")
            )
    return lines


def report(rows: list[dict], model: str) -> str:
    table = pd.DataFrame(rows)
    by_category = table.groupby("category", sort=False).agg(
        questions=("passed", "size"), passed=("passed", "sum")
    )
    lines = [
        "# Ask the data: evaluation",
        "",
        f"Models (in fallback order): `{model}` · run {datetime.now():%Y-%m-%d %H:%M} · "
        f"{int(table['passed'].sum())} of {len(table)} correct "
        f"({100 * table['passed'].mean():.0f}%) · median {table['seconds'].median():.1f} s "
        "per question",
        "",
        "Generated by `uv run python -m dbp.ask.evaluate`. Each answer is checked against a "
        "hand-written reference query (`src/dbp/ask/eval_questions.yml`).",
        "",
        *split_summary(table),
        "",
        "| Category | Questions | Correct |",
        "| --- | --- | --- |",
        *[
            f"| {name} | {row.questions} | {row.passed} |"
            for name, row in by_category.iterrows()
        ],
        "",
        "| Question | Check | Result | Attempts | Seconds |",
        "| --- | --- | --- | --- | --- |",
        *[
            f"| {row['question']} | {row['check']} "
            f"| {'✅' if row['passed'] else '❌ ' + row['note'].replace('|', '/')} "
            f"| {row['attempts']} | {row['seconds']} |"
            for row in rows
        ],
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--provider", help="e.g. mistral or groq (default: LLM_PROVIDERS)")
    parser.add_argument("--model", help="model of the first provider")
    parser.add_argument("--only", help="run only question ids containing this text")
    parser.add_argument(
        "--pause", type=float, default=0, help="seconds between questions (free-plan limits)"
    )
    parser.add_argument("--output", type=Path, default=DOCS / "ask_eval.md")
    args = parser.parse_args()

    items = yaml.safe_load(QUESTIONS.read_text(encoding="utf-8"))["questions"]
    if args.only:
        items = [item for item in items if args.only in item["id"]]
    con = open_sandbox()
    llm = build_client(providers=args.provider, model=args.model)
    label = " → ".join(client.label for client in llm.clients)
    rows = []
    for item in items:
        time.sleep(args.pause)
        result = ask(item["question"], con, llm)
        # An outage says nothing about answer quality: wait and ask again (up to 3 times).
        for _ in range(2):
            if not is_outage(result):
                break
            time.sleep(30)
            result = ask(item["question"], con, llm)
        passed = grade(item, result, con)
        note = describe(result)
        rows.append(
            {
                "id": item["id"],
                "category": item["category"],
                "question": item["question"],
                "check": item["check"],
                "passed": passed,
                "note": note,
                "attempts": result.attempts,
                "seconds": result.seconds,
                "model": result.model,
            }
        )
        print(
            f"{'PASS' if passed else 'FAIL'}  {item['id']:<28} {result.seconds:>5}s  "
            f"{result.status}  {' '.join(result.sql.split())[:110]}",
            flush=True,
        )
    args.output.write_text(report(rows, label), encoding="utf-8")
    print(f"\n{sum(r['passed'] for r in rows)} of {len(rows)} correct -> {args.output}")


if __name__ == "__main__":
    main()
