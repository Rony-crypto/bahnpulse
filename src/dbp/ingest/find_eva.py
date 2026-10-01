"""Look up EVA numbers for the hubs in config/hubs.yml via the Timetables station endpoint.

Usage:
    uv run python -m dbp.ingest.find_eva            # print candidates
    uv run python -m dbp.ingest.find_eva --write    # write exact-name matches into hubs.yml

Only exact name matches are written automatically; check the printed candidates for the rest.
"""

from __future__ import annotations

import argparse
import xml.etree.ElementTree as ET

import yaml

from dbp.config import CONFIG
from dbp.ingest.db_api import timetables_station

HUBS_FILE = CONFIG / "hubs.yml"


def parse_stations(xml_text: str) -> list[dict[str, str]]:
    """Parse <stations><station name=".." eva=".." ds100=".."/></stations>."""
    root = ET.fromstring(xml_text)
    return [dict(s.attrib) for s in root.iter("station")]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="write exact matches to hubs.yml")
    args = parser.parse_args()

    config = yaml.safe_load(HUBS_FILE.read_text(encoding="utf-8"))
    changed = 0
    for hub in config["hubs"]:
        if hub.get("eva"):
            continue
        candidates = parse_stations(timetables_station(hub["name"]))
        exact = [c for c in candidates if c.get("name") == hub["name"]]
        shown = ", ".join(f"{c.get('name')}={c.get('eva')}" for c in candidates[:5]) or "none"
        print(f"{hub['name']:<22} -> {shown}")
        if args.write and len(exact) == 1:
            hub["eva"] = exact[0]["eva"]
            changed += 1

    if args.write and changed:
        HUBS_FILE.write_text(
            yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
        print(f"wrote {changed} EVA numbers to {HUBS_FILE}")


if __name__ == "__main__":
    main()
