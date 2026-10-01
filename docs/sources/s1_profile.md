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
| 2026-06 | 15082144 |
| 2026-07 | 14768104 |
| 2026-08 | 14516986 |

## Train types

| train_type | rows | pct |
|---|---|---|
| S | 19340563 | 43.59 |
| RB | 5459213 | 12.3 |
| RE | 4128737 | 9.31 |
| Bus | 1195687 | 2.69 |
| HLB | 1033642 | 2.33 |
| ARV | 749495 | 1.69 |
| BRB | 686209 | 1.55 |
| NWB | 631936 | 1.42 |
| OE | 630540 | 1.42 |
| ERB | 625564 | 1.41 |
|  | 606209 | 1.37 |
| ICE | 562773 | 1.27 |
| NX | 562208 | 1.27 |
| VIA | 541965 | 1.22 |
| SWE | 534399 | 1.2 |
| ag | 503319 | 1.13 |
| SBH | 485166 | 1.09 |
| vlx | 444679 | 1.0 |
| AVG | 437153 | 0.99 |
| EB | 384935 | 0.87 |
| ABR | 344743 | 0.78 |
| MRB | 306951 | 0.69 |
| NEB | 295036 | 0.66 |
| NBE | 294607 | 0.66 |
| STB | 293919 | 0.66 |
| RRB | 272298 | 0.61 |
| SBB | 270585 | 0.61 |
| RSM | 247917 | 0.56 |
| erx | 241466 | 0.54 |
| TR | 206283 | 0.46 |

## Hamburg S-Bahn lines

| line_number | stops | stations |
|---|---|---|
| S1 | 87425 | 4 |
| S3 | 85900 | 5 |
| S5 | 85835 | 6 |
| S2 | 55148 | 4 |
| S7 | 28641 | 4 |
| S0 | 10 | 5 |

## Null rate per column (%)

| station_name | xml_station_name | eva | train_number | line_number | final_destination_station | delay_in_min | time | arrival_is_canceled | departure_is_canceled | train_type | is_additional_stop | is_replacement_train | replaced_train_number | train_line_ride_id | train_line_station_num | arrival_planned_time | arrival_change_time | departure_planned_time | departure_change_time | id |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0.03 | 0.0 | 0.0 | 1.37 | 1.93 | 9.18 | 1.37 | 0.0 | 0.0 | 0.0 | 1.37 | 0.0 | 0.0 | 99.32 | 0.0 | 0.0 | 9.16 | 7.91 | 9.18 | 7.92 | 0.0 |

## Duplicate candidate key (eva, train_number, planned time)

| rows | distinct_keys | duplicates |
|---|---|---|
| 44367234 | 43762421 | 604813 |

## Hours without any planned stop (possible collection gaps)

| month | missing_hours |
|---|---|
