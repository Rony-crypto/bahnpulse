"""Download DB StaDa station master data and derive an EVA-to-state lookup.

Usage:
    uv run python -m dbp.ingest.download_s3

Raw API pages are retained under data/raw/s3/stations/. The normalized lookup is
written to data/raw/s3/station_state_map.csv for profiling and downstream models.
"""

from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from dbp.config import CONFIG, RAW_S1, RAW_S3
from dbp.ingest.db_api import stada_stations

PAGE_SIZE = 10_000
STATE_MAP = RAW_S3 / "station_state_map.csv"
STATE_OVERRIDES = CONFIG / "station_state_overrides.csv"


def fetch_all_pages(fetch_page=stada_stations, page_size: int = PAGE_SIZE) -> list[dict]:
    """Fetch all StaDa search results using the API's total and pagination fields."""
    first = fetch_page("*", offset=0, limit=page_size)
    total = int(first.get("total", len(first.get("result", []))))
    pages = [first]
    offset = len(first.get("result", []))

    while offset < total:
        page = fetch_page("*", offset=offset, limit=page_size)
        records = page.get("result", [])
        if not records:
            raise RuntimeError(f"StaDa returned an empty page at offset {offset} of {total}.")
        pages.append(page)
        offset += len(records)

    if offset != total:
        raise RuntimeError(f"StaDa reported {total} records but returned {offset}.")
    return pages


def build_eva_map(stations: list[dict]) -> tuple[list[dict], int]:
    """Expand station-level federal state and coordinates to one row per EVA number."""
    rows = []
    seen_evas = set()
    stations_without_eva = 0

    for station in stations:
        name = station.get("name")
        federal_state = station.get("federalState")
        evas = station.get("evaNumbers") or []
        if not evas:
            stations_without_eva += 1
            continue
        if not federal_state:
            raise ValueError(f"StaDa station {name!r} has EVA numbers but no federalState.")

        for eva in evas:
            number = eva.get("number")
            if number is None:
                continue
            eva_number = str(number)
            if eva_number in seen_evas:
                raise ValueError(f"StaDa returned duplicate EVA number {eva_number}.")
            seen_evas.add(eva_number)
            coordinates = eva.get("geographicCoordinates", {}).get("coordinates", [])
            rows.append(
                {
                    "eva": eva_number,
                    "station_name": name,
                    "federal_state": federal_state,
                    "longitude": coordinates[0] if len(coordinates) >= 2 else "",
                    "latitude": coordinates[1] if len(coordinates) >= 2 else "",
                    "category": station.get("category", ""),
                    "mapping_source": "StaDa",
                }
            )

    return rows, stations_without_eva


def apply_state_overrides(eva_rows: list[dict], overrides_path: Path) -> list[dict]:
    """Add curated state mappings for historical S1 stations absent from current StaDa."""
    by_eva = {row["eva"]: row for row in eva_rows}
    with overrides_path.open(encoding="utf-8", newline="") as source:
        for override in csv.DictReader(source):
            eva = override["eva"].strip()
            federal_state = override["federal_state"].strip()
            if not eva or not federal_state:
                raise ValueError("Station-state overrides require EVA and federal_state values.")
            existing = by_eva.get(eva)
            if existing:
                if existing["federal_state"] != federal_state:
                    raise ValueError(f"Override conflicts with StaDa for EVA {eva}.")
                continue
            row = {
                "eva": eva,
                "station_name": override["station_name"].strip(),
                "federal_state": federal_state,
                "longitude": "",
                "latitude": "",
                "category": "",
                "mapping_source": f"manual: {override['reason'].strip()}",
            }
            eva_rows.append(row)
            by_eva[eva] = row
    return eva_rows


def save_snapshot(
    pages: list[dict],
    eva_rows: list[dict],
    raw_root: Path = RAW_S3,
    state_map_path: Path = STATE_MAP,
    snapshot_id: str | None = None,
) -> Path:
    """Persist unmodified API payloads and the derived station lookup."""
    snapshot_id = snapshot_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    snapshot_dir = raw_root / "stations" / snapshot_id
    snapshot_dir.mkdir(parents=True, exist_ok=False)
    for index, page in enumerate(pages):
        path = snapshot_dir / f"page-{index:05d}.json"
        path.write_text(json.dumps(page, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    state_map_path.parent.mkdir(parents=True, exist_ok=True)
    columns = [
        "eva",
        "station_name",
        "federal_state",
        "longitude",
        "latitude",
        "category",
        "mapping_source",
    ]
    with state_map_path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=columns)
        writer.writeheader()
        writer.writerows(eva_rows)
    return snapshot_dir


def audit_s1_coverage(state_map_path: Path = STATE_MAP) -> tuple[int, int] | None:
    """Return unique S1 EVA count and number not found in the station-state map."""
    if not list(RAW_S1.glob("data-*.parquet")):
        return None

    map_path = state_map_path.as_posix().replace("'", "''")
    parquet_glob = (RAW_S1 / "data-*.parquet").as_posix().replace("'", "''")
    result = duckdb.sql(
        f"""
        SELECT count(*) AS s1_evas,
               count(*) FILTER (WHERE states.eva IS NULL) AS unmapped_evas
        FROM (
            SELECT DISTINCT CAST(eva AS VARCHAR) AS eva
            FROM read_parquet('{parquet_glob}')
            WHERE eva IS NOT NULL AND trim(CAST(eva AS VARCHAR)) <> ''
        ) source
                LEFT JOIN read_csv('{map_path}', all_varchar=true) states
                    ON CASE
                                 WHEN length(source.eva) = 8 AND starts_with(source.eva, '08')
                                 THEN substring(source.eva, 2)
                                 ELSE source.eva
                         END = states.eva
        """
    ).fetchone()
    return int(result[0]), int(result[1])


def main() -> None:
    pages = fetch_all_pages()
    stations = [station for page in pages for station in page.get("result", [])]
    eva_rows, stations_without_eva = build_eva_map(stations)
    eva_rows = apply_state_overrides(eva_rows, STATE_OVERRIDES)
    snapshot_dir = save_snapshot(pages, eva_rows)

    print(f"Fetched {len(stations)} station records and {len(eva_rows)} EVA mappings.")
    print(f"Stations without an EVA number: {stations_without_eva}.")
    print(f"Raw API pages saved to {snapshot_dir}.")
    print(f"Derived state lookup saved to {STATE_MAP}.")

    coverage = audit_s1_coverage()
    if coverage is not None:
        s1_evas, unmapped_evas = coverage
        mapped = s1_evas - unmapped_evas
        percentage = 100.0 * mapped / s1_evas if s1_evas else 100.0
        print(
            f"S1 EVA coverage: {mapped}/{s1_evas} "
            f"({percentage:.2f}%), unmapped: {unmapped_evas}."
        )
        if unmapped_evas:
            raise SystemExit("Some S1 EVA numbers are missing from the StaDa station lookup.")


if __name__ == "__main__":
    main()