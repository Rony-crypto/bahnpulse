from datetime import date

from dbp.publish.check_new_month import is_stale, new_month


def test_new_month_only_when_source_is_ahead():
    assert new_month("2026-09", "2026-08") == "2026-09"
    assert new_month("2026-09", "2026-09") is None
    assert new_month("2026-09", None) == "2026-09"


def test_is_stale_40_days_after_newest_month_ends():
    # Newest month Sep 2026 ends 30 Sep; stale from 10 Nov (October should be out by then).
    assert not is_stale("2026-09", date(2026, 11, 9))
    assert is_stale("2026-09", date(2026, 11, 10))
