import csv

import pytest

from dbp.ingest.download_s3 import (
    apply_state_overrides,
    build_eva_map,
    fetch_all_pages,
    save_snapshot,
)


def test_fetch_all_pages_uses_reported_total():
    responses = {
        0: {"offset": 0, "total": 3, "result": [{"name": "A"}, {"name": "B"}]},
        2: {"offset": 2, "total": 3, "result": [{"name": "C"}]},
    }
    requested_offsets = []

    def fetch_page(searchstring, offset, limit):
        requested_offsets.append(offset)
        return responses[offset]

    pages = fetch_all_pages(fetch_page, page_size=2)

    assert requested_offsets == [0, 2]
    assert [record["name"] for page in pages for record in page["result"]] == ["A", "B", "C"]


def test_build_eva_map_expands_coordinates_and_counts_missing_evas():
    stations = [
        {
            "name": "Hamburg Hbf",
            "federalState": "Hamburg",
            "category": 1,
            "evaNumbers": [
                {"number": 8002549, "geographicCoordinates": {"coordinates": [10.0, 53.5]}},
                {"number": 8098549},
            ],
        },
        {"name": "No EVA", "federalState": "Hamburg", "evaNumbers": []},
    ]

    rows, missing = build_eva_map(stations)

    assert len(rows) == 2
    assert rows[0]["eva"] == "8002549"
    assert rows[0]["longitude"] == 10.0
    assert rows[0]["latitude"] == 53.5
    assert rows[1]["longitude"] == ""
    assert missing == 1


def test_build_eva_map_rejects_duplicate_eva_numbers():
    stations = [
        {"name": "A", "federalState": "Hamburg", "evaNumbers": [{"number": 1}]},
        {"name": "B", "federalState": "Hamburg", "evaNumbers": [{"number": 1}]},
    ]

    with pytest.raises(ValueError, match="duplicate EVA number"):
        build_eva_map(stations)


def test_apply_state_overrides_adds_absent_evas_and_rejects_conflicts(tmp_path):
    override_path = tmp_path / "overrides.csv"
    override_path.write_text(
        "eva,station_name,federal_state,reason\n"
        "8012505,Niederwürschnitz,Sachsen,legacy station\n",
        encoding="utf-8",
    )
    rows = []

    result = apply_state_overrides(rows, override_path)

    assert result[0]["eva"] == "8012505"
    assert result[0]["federal_state"] == "Sachsen"
    assert result[0]["mapping_source"] == "manual: legacy station"


def test_save_snapshot_preserves_pages_and_writes_state_map(tmp_path):
    pages = [{"offset": 0, "total": 1, "result": [{"name": "Hamburg Hbf"}]}]
    eva_rows = [
        {
            "eva": "8002549",
            "station_name": "Hamburg Hbf",
            "federal_state": "Hamburg",
            "longitude": 10.0,
            "latitude": 53.5,
            "category": 1,
            "mapping_source": "StaDa",
        }
    ]

    snapshot = save_snapshot(pages, eva_rows, tmp_path / "raw", tmp_path / "map.csv", "test-run")

    assert (snapshot / "page-00000.json").read_text(encoding="utf-8").find('"total": 1') >= 0
    with (tmp_path / "map.csv").open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))
    assert rows[0]["eva"] == "8002549"
    assert rows[0]["federal_state"] == "Hamburg"