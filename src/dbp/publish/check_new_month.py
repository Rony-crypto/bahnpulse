"""Decide whether the monthly job has work to do: is a newer S1 month published than the one
the app already shows? Runs daily, so a month that appears late is picked up the next morning.

Usage:
    uv run python -m dbp.publish.check_new_month

Prints new_month=<YYYY-MM or empty> and writes it to $GITHUB_OUTPUT when run in Actions.
Exits with an error when the source is stale (TRD freshness rule: error when the newest
published month ended more than 40 days ago), so GitHub reports the failure.
"""

from __future__ import annotations

import json
import os
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from dbp.ingest.download_s1 import latest_published_month
from dbp.publish.export_marts import PUBLISHED

STALE_AFTER_DAYS = 40


def new_month(latest: str, shown: str | None) -> str | None:
    """The latest published month if the app does not show it yet, else None."""
    return latest if shown is None or latest > shown else None


def is_stale(latest: str, today: date, stale_after_days: int = STALE_AFTER_DAYS) -> bool:
    """True when the newest published month ended more than stale_after_days ago."""
    latest_end = pd.Period(latest, freq="M").end_time.date()
    return today > latest_end + timedelta(days=stale_after_days)


def shown_month(published: Path = PUBLISHED) -> str | None:
    status_path = published / "run_status.json"
    if not status_path.exists():
        return None
    return json.loads(status_path.read_text(encoding="utf-8")).get("source_month_end")


def main() -> None:
    latest = latest_published_month()
    shown = shown_month()
    found = new_month(latest, shown)
    print(f"source latest: {latest} · app shows: {shown} · new_month={found or ''}")
    output = os.getenv("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"new_month={found or ''}\n")
    if is_stale(latest, date.today()):
        raise SystemExit(
            f"S1 source looks stale: newest month {latest} ended more than "
            f"{STALE_AFTER_DAYS} days ago and no newer month is published."
        )


if __name__ == "__main__":
    main()
