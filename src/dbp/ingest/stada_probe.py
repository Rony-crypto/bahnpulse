"""Week 1 check: does StaDa give us federal state and coordinates for each station?

Usage:
    uv run python -m dbp.ingest.stada_probe "Hamburg Hbf"

Prints the fields of the first match and saves the full response to data/raw/s3/probe.json.
Look for: federalState, evaNumbers (with geographicCoordinates), number.
If the state is missing, the fallback is a spatial join of coordinates with the
Bundeslaender GeoJSON (see TRD section 3).
"""

from __future__ import annotations

import json
import sys

from dbp.config import RAW_S3
from dbp.ingest.db_api import stada_stations

FIELDS_WE_NEED = ["name", "federalState", "evaNumbers", "category", "number"]


def main() -> None:
    query = sys.argv[1] if len(sys.argv) > 1 else "Hamburg Hbf"
    data = stada_stations(query)
    RAW_S3.mkdir(parents=True, exist_ok=True)
    (RAW_S3 / "probe.json").write_text(json.dumps(data, indent=2, ensure_ascii=False))

    stations = data.get("result", [])
    print(f"{len(stations)} station(s) found for {query!r}")
    if not stations:
        return
    first = stations[0]
    print("All top-level fields:", sorted(first.keys()))
    for field in FIELDS_WE_NEED:
        status = "OK " if field in first else "MISSING"
        value = json.dumps(first.get(field), ensure_ascii=False)[:160]
        print(f"  [{status}] {field}: {value}")


if __name__ == "__main__":
    main()
