import pandas as pd

from dbp.dashboard.charts import delay_breakdown
from dbp.dashboard.data import (
    delay_sources,
    headline_kpis,
    summarize_cancellations,
    summarize_stations,
    summarize_weekly,
    top_share,
)
from dbp.dashboard.hamburg import cancellation_table


def test_summarize_weekly_weights_time_slots_by_delay_count():
    frame = pd.DataFrame(
        [
            {
                "item_key": "S1",
                "service_week": "2026-01-05",
                "stop_count": 10,
                "arrival_count": 1,
                "on_time_arrival_count": 1,
                "delay_count": 1,
                "delay_total_min": 10,
            },
            {
                "item_key": "S1",
                "service_week": "2026-01-05",
                "stop_count": 30,
                "arrival_count": 3,
                "on_time_arrival_count": 2,
                "delay_count": 3,
                "delay_total_min": 90,
            },
        ]
    )

    weekly = summarize_weekly(frame)

    assert weekly.loc[0, "avg_arrival_delay_min"] == 25
    assert weekly.loc[0, "punctuality_pct"] == 75

def test_summarize_stations_sorts_worst_first_and_keeps_zero_arrivals_last():
    frame = pd.DataFrame(
        [
            {"station_name": "A", "federal_state": "Hamburg",
             "planned_stop_count": 100, "arrival_count": 95,
             "on_time_arrival_count": 86, "cancelled_arrival_count": 5},
            {"station_name": "A", "federal_state": "Hamburg",
             "planned_stop_count": 100, "arrival_count": 95,
             "on_time_arrival_count": 66, "cancelled_arrival_count": 5},
            {"station_name": "B", "federal_state": "Hamburg",
             "planned_stop_count": 50, "arrival_count": 50,
             "on_time_arrival_count": 25, "cancelled_arrival_count": 0},
            {"station_name": "C", "federal_state": "Bayern",
             "planned_stop_count": 4, "arrival_count": 0,
             "on_time_arrival_count": 0, "cancelled_arrival_count": 4},
        ]
    )

    stations = summarize_stations(frame)

    assert stations["station_name"].tolist() == ["B", "A", "C"]
    assert stations.loc[1, "punctuality_pct"] == 80
    assert stations.loc[1, "cancellation_pct"] == 5
    assert pd.isna(stations.loc[2, "punctuality_pct"])


def test_headline_kpis_weights_states_by_volume():
    summary = pd.DataFrame(
        [
            {"planned_stop_count": 100, "cancelled_arrival_count": 90, "arrival_count": 80,
             "on_time_arrival_count": 40, "avg_arrival_delay_min": 10.0},
            {"planned_stop_count": 300, "cancelled_arrival_count": 10, "arrival_count": 320,
             "on_time_arrival_count": 288, "avg_arrival_delay_min": 2.5},
        ]
    )

    kpis = headline_kpis(summary)

    assert kpis["punctuality"] == 82
    assert kpis["delay"] == 4
    # Cancelled share of planned arrivals: 100 cancelled of 500 planned.
    assert kpis["cancelled"] == 20
    assert kpis["stops"] == 400


def test_headline_kpis_handles_empty_selection():
    empty = pd.DataFrame(
        columns=["planned_stop_count", "cancelled_arrival_count", "arrival_count",
                 "on_time_arrival_count", "avg_arrival_delay_min"]
    )

    kpis = headline_kpis(empty)

    assert pd.isna(kpis["punctuality"]) and kpis["stops"] == 0


def test_delay_breakdown_shares_add_up_per_train_type():
    frame = pd.DataFrame(
        [
            {"train_group": "RE", "on_time_arrival_count": 60, "delay_6_15_count": 20,
             "delay_16_30_count": 10, "delay_31_60_count": 5, "delay_over_60_count": 0,
             "cancelled_arrival_count": 5},
            {"train_group": "ICE", "on_time_arrival_count": 1, "delay_6_15_count": 0,
             "delay_16_30_count": 0, "delay_31_60_count": 0, "delay_over_60_count": 1,
             "cancelled_arrival_count": 0},
        ]
    )

    overall = delay_breakdown(frame)
    by_type = delay_breakdown(frame, by="train_group")

    assert overall["count"].sum() == 102
    assert overall.loc[overall["bucket"] == "On time (<6 min)", "count"].iloc[0] == 61
    assert by_type.groupby("train_group")["share_pct"].sum().round(6).eq(100).all()
    re_late = by_type.query("train_group == 'RE' and bucket == '6–15 min late'")
    assert re_late["share_pct"].iloc[0] == 20


def test_summarize_cancellations_uses_planned_arrivals_and_sorts_worst_first():
    frame = pd.DataFrame(
        {
            "train_group": ["RE", "RE", "S", "ICE"],
            "arrival_count": [90, 290, 198, 0],
            "cancelled_arrival_count": [10, 10, 2, 0],
        }
    )

    cancelled = summarize_cancellations(frame, "train_group")

    assert cancelled["train_group"].tolist() == ["RE", "S"]
    assert cancelled.loc[0, "cancelled_pct"] == 5
    assert cancelled.loc[1, "cancelled_pct"] == 1


def test_cancellation_table_names_worst_week_and_drops_small_items():
    frame = pd.DataFrame(
        {
            "item_key": ["S1", "S1", "S1", "S9"],
            "service_week": ["2026-01-05", "2026-01-12", "2026-01-19", "2026-01-05"],
            "arrival_count": [57, 24, 5, 49],
            "cancelled_arrival_count": [3, 6, 5, 1],
        }
    )

    table = cancellation_table(frame)

    assert table["item"].tolist() == ["S1"]
    assert table.loc[0, "cancelled_pct"] == 14
    # The 10-arrival week has the highest share but too few arrivals to count.
    assert table.loc[0, "worst"] == "week of 12 Jan 2026 (20%)"


def test_delay_sources_shares_cover_only_trips_that_end_late():
    frame = pd.DataFrame(
        {
            "train_group": ["ICE", "ICE", "S"],
            "ends_late": [True, False, True],
            "trip_count": [10, 30, 4],
            "origin_late_min": [20, 99, 10],
            "running_added_min": [60, 99, 10],
            "dwell_added_min": [20, 99, 20],
            "final_late_min": [150, 99, 40],
        }
    )

    sources = delay_sources(frame).set_index("train_group")

    assert sources.index.tolist() == ["ICE", "S"]
    assert sources.loc["ICE", "running_pct"] == 60
    assert sources.loc["ICE", "late_trip_pct"] == 25
    assert sources.loc["ICE", "avg_final_late_min"] == 15
    assert sources.loc["S", "dwell_pct"] == 50


def test_top_share_takes_the_largest_values():
    values = pd.Series([50, 10, 10, 10, 10, 10] + [0] * 34)

    assert top_share(values, 0.05) == 60  # top 2 of 40: 50 + 10 of 100

