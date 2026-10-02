import pytest

from dbp.ingest.download_s1 import file_name, file_url, months_between, months_in_listing


def test_months_between_crosses_year():
    assert months_between("2025-11", "2026-02") == ["2025-11", "2025-12", "2026-01", "2026-02"]


def test_months_between_single_month():
    assert months_between("2026-08", "2026-08") == ["2026-08"]


def test_months_between_rejects_reversed_range():
    with pytest.raises(ValueError):
        months_between("2026-08", "2026-06")


def test_file_name_and_url():
    assert file_name("2026-08") == "data-2026-08.parquet"
    assert file_url("2026-08").endswith("/monthly_processed_data/data-2026-08.parquet")


def test_file_name_rejects_invalid_month():
    with pytest.raises(ValueError):
        file_name("2026-13")


def test_months_in_listing_keeps_only_monthly_files_sorted():
    paths = [
        "monthly_processed_data/data-2026-09.parquet",
        "monthly_processed_data/README.md",
        "monthly_processed_data/data-2025-11.parquet",
        "monthly_processed_data/data-2026-08.parquet",
    ]
    assert months_in_listing(paths) == ["2025-11", "2026-08", "2026-09"]
