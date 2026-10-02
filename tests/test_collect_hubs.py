import gzip
import json
from datetime import datetime
from pathlib import Path

import requests

from dbp.ingest.collect_hubs import BERLIN, fetch_and_store, run_calls, write_log

HUB = {"name": "Hamburg Hbf", "state": "Hamburg", "eva": "8002549"}
NOW = datetime(2026, 10, 2, 23, 5, 7, tzinfo=BERLIN)


def test_run_calls_adds_plan_for_three_hours_across_midnight():
    calls = run_calls([HUB], NOW, with_plan=True)

    assert [c.endpoint for c in calls] == ["fchg", "plan", "plan", "plan"]
    assert calls[0].url.endswith("/fchg/8002549")
    assert [c.url.rsplit("/", 2)[-2:] for c in calls[1:]] == [
        ["261002", "23"], ["261003", "00"], ["261003", "01"]
    ]
    assert calls[0].path == Path("8002549/2026-10-02/230507_fchg.xml.gz")


def test_run_calls_without_plan_only_fetches_changes():
    assert [c.endpoint for c in run_calls([HUB], NOW, with_plan=False)] == ["fchg"]


class FakeResponse:
    def __init__(self, status_code, content=b""):
        self.status_code, self.content = status_code, content


def fake_fetch(url, accept):
    if "/plan/" in url:
        response = FakeResponse(404)
        raise requests.HTTPError("404 Not Found", response=response)
    return FakeResponse(200, b"<timetable station='Hamburg Hbf'/>")


def test_fetch_and_store_gzips_bodies_and_records_failures(tmp_path):
    records = fetch_and_store(run_calls([HUB], NOW, with_plan=True), tmp_path, fetch=fake_fetch)

    stored = tmp_path / "8002549/2026-10-02/230507_fchg.xml.gz"
    assert gzip.decompress(stored.read_bytes()) == b"<timetable station='Hamburg Hbf'/>"
    assert records[0]["status"] == 200 and records[0]["bytes"] == 34
    assert [r["status"] for r in records[1:]] == [404, 404, 404]
    assert all("file" not in r for r in records[1:])


def test_write_log_is_one_file_per_run(tmp_path):
    path = write_log([{"eva": "8002549", "status": 200}], tmp_path, NOW)

    assert path == Path("_log/2026-10-02/230507.jsonl")
    assert json.loads((tmp_path / path).read_text()) == {"eva": "8002549", "status": 200}
