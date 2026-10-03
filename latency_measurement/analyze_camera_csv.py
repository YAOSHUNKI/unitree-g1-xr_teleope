#!/usr/bin/env python3
"""Summarize camera capture-to-browser-display latency CSV files."""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path
from statistics import mean


def percentile(values, percent):
    ordered = sorted(values)
    position = (len(ordered) - 1) * percent / 100
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def main():
    parser = argparse.ArgumentParser(description="Summarize camera latency CSV")
    parser.add_argument("csv_file", type=Path)
    args = parser.parse_args()

    with args.csv_file.open(newline="", encoding="utf-8") as csv_file:
        rows = list(csv.DictReader(csv_file))
    if not rows:
        raise SystemExit("CSV contains no samples")

    values = [float(row["latency_ms"]) for row in rows]
    missing = 0
    duplicates = 0
    previous = None
    for row in rows:
        sequence = int(row["sequence"])
        if previous is not None:
            delta = (sequence - previous) & 0xFFFFFFFF
            if delta == 0:
                duplicates += 1
            elif delta < 0x80000000:
                missing += max(0, delta - 1)
        previous = sequence

    print(f"samples={len(values)} missing_frames={missing} duplicates={duplicates}")
    print(
        "latency_ms "
        f"min={min(values):.3f} mean={mean(values):.3f} "
        f"p50={percentile(values, 50):.3f} "
        f"p95={percentile(values, 95):.3f} "
        f"p99={percentile(values, 99):.3f} max={max(values):.3f}"
    )


if __name__ == "__main__":
    main()
