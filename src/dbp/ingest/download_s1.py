"""Download monthly S1 history files (piebro/deutsche-bahn-data on Hugging Face).

Usage:
    uv run python -m dbp.ingest.download_s1 --start 2026-06 --end 2026-08

Files land unchanged in data/raw/s1/. Re-running skips files that are already complete,
so the script is safe to run again (idempotent).
"""

from __future__ import annotations

import argparse
import logging
from datetime import date
from pathlib import Path

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from dbp.config import RAW_S1

log = logging.getLogger(__name__)

BASE_URL = (
    "https://huggingface.co/datasets/piebro/deutsche-bahn-data/resolve/main/monthly_processed_data"
)


def months_between(start: str, end: str) -> list[str]:
    """Return all months 'YYYY-MM' from start to end, inclusive."""
    y, m = map(int, start.split("-"))
    end_y, end_m = map(int, end.split("-"))
    if (y, m) > (end_y, end_m):
        raise ValueError(f"start {start} is after end {end}")
    out = []
    while (y, m) <= (end_y, end_m):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def file_name(month: str) -> str:
    date.fromisoformat(f"{month}-01")  # validates the month string
    return f"data-{month}.parquet"


def file_url(month: str) -> str:
    return f"{BASE_URL}/{file_name(month)}"


@retry(stop=stop_after_attempt(4), wait=wait_exponential(min=2, max=30), reraise=True)
def _remote_size(url: str) -> int | None:
    r = requests.head(url, allow_redirects=True, timeout=30)
    r.raise_for_status()
    size = r.headers.get("Content-Length")
    return int(size) if size else None


@retry(stop=stop_after_attempt(4), wait=wait_exponential(min=2, max=30), reraise=True)
def _download(url: str, target: Path) -> None:
    tmp = target.with_suffix(".part")
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        with tmp.open("wb") as f:
            for chunk in r.iter_content(chunk_size=8 * 1024 * 1024):
                f.write(chunk)
    tmp.replace(target)  # atomic: a half-written file never looks complete


def download_month(month: str, out_dir: Path = RAW_S1) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    url = file_url(month)
    target = out_dir / file_name(month)
    remote = _remote_size(url)
    if target.exists() and remote is not None and target.stat().st_size == remote:
        log.info("skip %s (already complete, %.0f MB)", target.name, remote / 1e6)
        return target
    log.info("download %s (%s MB)", url, f"{remote / 1e6:.0f}" if remote else "?")
    _download(url, target)
    log.info("saved %s", target)
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--start", required=True, help="first month, YYYY-MM")
    parser.add_argument("--end", required=True, help="last month, YYYY-MM")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    for month in months_between(args.start, args.end):
        download_month(month)


if __name__ == "__main__":
    main()
