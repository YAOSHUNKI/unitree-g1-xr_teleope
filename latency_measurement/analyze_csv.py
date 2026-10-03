#!/usr/bin/env python3
"""Summarize latency CSV files without third-party dependencies."""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path
from statistics import mean


METRICS = [
    "browser_to_xr_raw_ms",
    "browser_to_xr_ms",
    "xr_processing_ms",
    "wan_raw_ms",
    "wan_ms",
    "ros_delivery_ms",
    "end_to_end_raw_ms",
    "end_to_end_ms",
]


def percentile(values: list[float], percent: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percent / 100
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def main():
    parser = argparse.ArgumentParser(description="Summarize an XR latency CSV")
    parser.add_argument("csv_file", type=Path)
    args = parser.parse_args()

    rows_by_topic: dict[str, list[dict[str, str]]] = {}
    with args.csv_file.open(newline="", encoding="utf-8") as csv_file:
        for row in csv.DictReader(csv_file):
            rows_by_topic.setdefault(row["topic"], []).append(row)

    if not rows_by_topic:
        raise SystemExit("CSV contains no samples")

    for topic, rows in sorted(rows_by_topic.items()):
        missing = sum(int(row["sequence_gap"]) for row in rows)
        expected = len(rows) + missing
        loss_percent = 100 * missing / expected if expected else 0.0
        print(f"\n[{topic}] samples={len(rows)} missing_updates={missing} loss={loss_percent:.3f}%")
        print("metric                         min      mean       p50       p95       p99       max")
        for metric in METRICS:
            values = [float(row[metric]) for row in rows]
            print(
                f"{metric:27s} "
                f"{min(values):9.3f} {mean(values):9.3f} "
                f"{percentile(values, 50):9.3f} {percentile(values, 95):9.3f} "
                f"{percentile(values, 99):9.3f} {max(values):9.3f}"
            )


if __name__ == "__main__":
    main()
