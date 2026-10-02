"""Collect near-real-time Timetables data (S2) for the hubs in config/hubs.yml (FR-03).

Usage:
    uv run python -m dbp.ingest.collect_hubs --state Hamburg --no-upload   # local test
    uv run python -m dbp.ingest.collect_hubs --state Hamburg --plan        # Actions, hourly

Every run calls fchg (all known changes) per hub; with --plan (or in the first quarter of an
hour) it also calls plan for the current and next two hours. Responses are stored unchanged
(gzipped) with the fetch time in the path, plus one JSON line per call (status, size,
duration) for the reliability test. With HF_S2_REPO set, the run's files are uploaded to that
private Hugging Face dataset, because a GitHub runner keeps nothing between runs.
"""

from __future__ import annotations

import argparse
import gzip
import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
import yaml

from dbp.config import CONFIG, RAW_S2, env
from dbp.ingest import db_api

log = logging.getLogger(__name__)

BERLIN = ZoneInfo("Europe/Berlin")
PLAN_HOURS_AHEAD = 2


@dataclass(frozen=True)
class Call:
    eva: str
    name: str
    endpoint: str  # "fchg" or "plan"
    url: str
    path: Path  # where the gzipped response is stored, relative to the S2 root


def load_hubs(state: str | None = None, hubs_file: Path = CONFIG / "hubs.yml") -> list[dict]:
    hubs = yaml.safe_load(hubs_file.read_text(encoding="utf-8"))["hubs"]
    hubs = [hub for hub in hubs if state is None or hub["state"] == state]
    missing = [hub["name"] for hub in hubs if not hub.get("eva")]
    if missing:
        raise SystemExit(f"Hubs without an EVA number: {missing}. Run dbp.ingest.find_eva.")
    return hubs


def plan_calls(hub: dict, now: datetime) -> list[Call]:
    """plan calls for the current hour and the next PLAN_HOURS_AHEAD hours (Berlin time)."""
    calls = []
    for offset in range(PLAN_HOURS_AHEAD + 1):
        slot = now + timedelta(hours=offset)
        date_part, hour_part = slot.strftime("%y%m%d"), slot.strftime("%H")
        calls.append(
            Call(
                eva=str(hub["eva"]),
                name=hub["name"],
                endpoint="plan",
                url=f"{db_api.TIMETABLES}/plan/{hub['eva']}/{date_part}/{hour_part}",
                path=Path(str(hub["eva"]))
                / now.strftime("%Y-%m-%d")
                / f"{now:%H%M%S}_plan_{date_part}{hour_part}.xml.gz",
            )
        )
    return calls


def run_calls(hubs: list[dict], now: datetime, with_plan: bool) -> list[Call]:
    calls = []
    for hub in hubs:
        calls.append(
            Call(
                eva=str(hub["eva"]),
                name=hub["name"],
                endpoint="fchg",
                url=f"{db_api.TIMETABLES}/fchg/{hub['eva']}",
                path=Path(str(hub["eva"])) / now.strftime("%Y-%m-%d") / f"{now:%H%M%S}_fchg.xml.gz",
            )
        )
        if with_plan:
            calls.extend(plan_calls(hub, now))
    return calls


def fetch_and_store(calls: list[Call], root: Path, fetch=db_api.get) -> list[dict]:
    """Fetch each call, store the body gzipped, and return one log record per call."""
    records = []
    for call in calls:
        started = time.monotonic()
        record = {
            "fetched_at": datetime.now(BERLIN).isoformat(timespec="seconds"),
            "eva": call.eva,
            "name": call.name,
            "endpoint": call.endpoint,
            "url_path": call.url.removeprefix(db_api.TIMETABLES),
        }
        try:
            response = fetch(call.url, accept="application/xml")
            body = response.content
            target = root / call.path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(gzip.compress(body))
            record |= {"status": response.status_code, "bytes": len(body),
                       "gz_bytes": target.stat().st_size, "file": str(call.path)}
        except requests.HTTPError as error:
            # plan returns 404 for hours without trains; keep going and record it.
            status = error.response.status_code if error.response is not None else None
            record |= {"status": status, "error": str(error)[:200]}
        except Exception as error:  # noqa: BLE001 - one failing hub must not stop the run
            record |= {"status": None, "error": f"{type(error).__name__}: {str(error)[:200]}"}
        record["seconds"] = round(time.monotonic() - started, 2)
        records.append(record)
    return records


def write_log(records: list[dict], root: Path, now: datetime) -> Path:
    """One JSON-lines file per run, so uploads from separate runners never overwrite each other."""
    path = Path("_log") / now.strftime("%Y-%m-%d") / f"{now:%H%M%S}.jsonl"
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return path


def upload(paths: list[Path], root: Path, repo_id: str, now: datetime) -> None:
    from huggingface_hub import CommitOperationAdd, HfApi

    api = HfApi(token=env("HF_TOKEN"))
    api.create_repo(repo_id, repo_type="dataset", private=True, exist_ok=True)
    operations = [
        CommitOperationAdd(path_in_repo=f"s2/{path.as_posix()}", path_or_fileobj=str(root / path))
        for path in paths
    ]
    api.create_commit(
        repo_id=repo_id,
        repo_type="dataset",
        operations=operations,
        commit_message=f"S2 collect {now:%Y-%m-%d %H:%M} Europe/Berlin ({len(paths)} files)",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--state", help="only hubs in this federal state, e.g. Hamburg")
    parser.add_argument("--plan", action="store_true", help="also fetch plan, whatever the minute")
    parser.add_argument("--no-upload", action="store_true", help="keep files local only")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    now = datetime.now(BERLIN)
    hubs = load_hubs(args.state)
    calls = run_calls(hubs, now, with_plan=args.plan or now.minute < 15)
    records = fetch_and_store(calls, RAW_S2)
    log_path = write_log(records, RAW_S2, now)

    ok = [r for r in records if r.get("file")]
    log.info(
        "%d/%d calls stored, %.1f MB raw, %.2f MB gzipped",
        len(ok), len(records),
        sum(r["bytes"] for r in ok) / 1e6, sum(r["gz_bytes"] for r in ok) / 1e6,
    )
    repo_id = os.getenv("HF_S2_REPO", "").strip()
    if repo_id and not args.no_upload:
        upload([Path(r["file"]) for r in ok] + [log_path], RAW_S2, repo_id, now)
        log.info("uploaded to hf://datasets/%s", repo_id)
    if not any(r["endpoint"] == "fchg" and r.get("file") for r in records):
        raise SystemExit("No fchg call succeeded in this run.")


if __name__ == "__main__":
    main()
