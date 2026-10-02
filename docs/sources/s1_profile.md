# S1 profile (generated)

## Schema

| column_name | column_type | null | key | default | extra |
|---|---|---|---|---|---|
| station_name | VARCHAR | YES |  |  |  |
| xml_station_name | VARCHAR | YES |  |  |  |
| eva | VARCHAR | YES |  |  |  |
| train_number | VARCHAR | YES |  |  |  |
| line_number | VARCHAR | YES |  |  |  |
| final_destination_station | VARCHAR | YES |  |  |  |
| delay_in_min | INTEGER | YES |  |  |  |
| time | TIMESTAMP_NS | YES |  |  |  |
| arrival_is_canceled | BOOLEAN | YES |  |  |  |
| departure_is_canceled | BOOLEAN | YES |  |  |  |
| train_type | VARCHAR | YES |  |  |  |
| is_additional_stop | BOOLEAN | YES |  |  |  |
| is_replacement_train | BOOLEAN | YES |  |  |  |
| replaced_train_number | VARCHAR | YES |  |  |  |
| train_line_ride_id | VARCHAR | YES |  |  |  |
| train_line_station_num | INTEGER | YES |  |  |  |
| arrival_planned_time | TIMESTAMP_NS | YES |  |  |  |
| arrival_change_time | TIMESTAMP_NS | YES |  |  |  |
| departure_planned_time | TIMESTAMP_NS | YES |  |  |  |
| departure_change_time | TIMESTAMP_NS | YES |  |  |  |
| id | VARCHAR | YES |  |  |  |
| _file | VARCHAR | YES |  |  |  |

## Rows per file

| month | rows |
|---|---|
| 2025-11 | 14206637 |
| 2025-12 | 15625384 |
| 2026-01 | 15799915 |
| 2026-02 | 13936132 |
| 2026-03 | 15240797 |
| 2026-04 | 14555946 |
| 2026-05 | 14906549 |
| 2026-06 | 15082144 |
| 2026-07 | 14768104 |
| 2026-08 | 14516986 |

## Train type groups

| train_group | rows | pct |
|---|---|---|
| S | 65976600 | 44.39 |
| RB | 44721878 | 30.09 |
| RE | 29554953 | 19.88 |
| Bus | 3906703 | 2.63 |
| ICE | 1904073 | 1.28 |
| Other | 1508974 | 1.02 |
| IC/EC | 1065413 | 0.72 |

## Train type codes

| train_type | train_group | rows |
|---|---|---|
| S | S | 65976055 |
| RB | RB | 19532827 |
| RE | RE | 14313384 |
| Bus | Bus | 3904388 |
| HLB | RE | 3445655 |
| BRB | RB | 2259129 |
| ARV | RB | 2120645 |
| NWB | RB | 2081162 |
| VIA | RE | 1912210 |
| ICE | ICE | 1904067 |
| ERB | RB | 1786106 |
| OE | RB | 1780524 |
| SWE | RE | 1765901 |
| ag | RB | 1710900 |
| NX | RE | 1546524 |
| (blank) | Other | 1470419 |
| SBH | RB | 1424553 |
| AVG | RB | 1255964 |
| vlx | RE | 1250850 |
| EB | RB | 1148735 |
| ABR | RB | 1045449 |
| NBE | RB | 1001463 |
| RRB | RB | 961845 |
| STB | RB | 919589 |
| RSM | RB | 903168 |
| SBB | RB | 886757 |
| MRB | RB | 866949 |
| NEB | RB | 839231 |
| erx | RE | 796944 |
| ME | RE | 673622 |
| TR | RB | 624004 |
| IC | IC/EC | 594240 |
| VBG | RE | 550802 |
| WFB | RE | 481130 |
| CAN | RE | 479456 |
| TL | RE | 429054 |
| RT | RE | 415718 |
| OPB | RE | 375469 |
| CB | RB | 306994 |
| WBA | RE | 268500 |

Bus rows are excluded from rail punctuality. Blank train types should be flagged as junk;
unmapped nonblank codes currently fall back to Other.

## Hamburg S-Bahn lines

| line_number | stops | stations |
|---|---|---|
| S1 | 3099191 | 51 |
| S3 | 1275641 | 48 |
| S5 | 1084269 | 46 |
| S7 | 549180 | 43 |
| 1 | 543302 | 40 |
| S2 | 410663 | 50 |
| 3 | 202670 | 39 |
| 5 | 164998 | 45 |
| 2 | 159047 | 28 |
| 0 | 368 | 30 |

S0 is excluded as an anomalous 10-stop line.

## Null rate per column (%)

| station_name | xml_station_name | eva | train_number | line_number | final_destination_station | delay_in_min | time | arrival_is_canceled | departure_is_canceled | train_type | is_additional_stop | is_replacement_train | replaced_train_number | train_line_ride_id | train_line_station_num | arrival_planned_time | arrival_change_time | departure_planned_time | departure_change_time | id |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0.02 | 0.0 | 0.0 | 0.99 | 1.97 | 8.58 | 0.99 | 0.0 | 0.0 | 0.0 | 0.99 | 0.0 | 0.0 | 99.49 | 0.0 | 0.0 | 8.59 | 7.67 | 8.58 | 7.67 | 0.0 |

## Change times without planned times

| arrival_change_without_plan | departure_change_without_plan |
|---|---|
| 1360329 | 1350214 |

## Duplicate candidate keys

| candidate_key | duplicate_rows |
|---|---|
| id | 0 |
| train_line_ride_id + train_line_station_num | 145387958 |
| ride + stop + planned time | 1135092 |

## Junk and rail-exclusion rows

| blank_train_type | blank_train_number | missing_delay | bus_rows |
|---|---|---|---|
| 1470419 | 1470419 | 1470419 | 3904388 |

## Hourly delay and change-time coverage

Hours are not considered gaps merely because they lack planned stops. Coverage below
half the month's median is flagged for investigation;
an empty table means none were flagged.

| hour | rows | delay_pct | change_time_pct | low_coverage |
|---|---|---|---|---|
| 2026-03-29 02:00 | 0 |  |  | True |
| 2026-04-08 03:00 | 0 |  |  | True |
