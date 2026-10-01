from dbp.ingest.find_eva import parse_stations

SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<stations>
  <station name="Hamburg Hbf" eva="1234567" ds100="AH"/>
  <station name="Hamburg Hbf (S-Bahn)" eva="7654321" ds100="AHS"/>
</stations>"""


def test_parse_stations_reads_attributes():
    stations = parse_stations(SAMPLE)
    assert [s["name"] for s in stations] == ["Hamburg Hbf", "Hamburg Hbf (S-Bahn)"]
    assert stations[0]["eva"] == "1234567"


def test_parse_stations_empty():
    assert parse_stations("<stations/>") == []
