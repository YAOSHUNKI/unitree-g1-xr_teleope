#!/usr/bin/env python3
"""Summarize Quest browser-to-XR PC input latency CSV files."""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path
from statistics import mean


def percentile(values: list[float], percent: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * percent / 100
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize browser-to-XR input latency")
    parser.add_argument("csv_file", type=Path)
    parser.add_argument(
        "--expected-hz",
        type=float,
        default=30.0,
        help="Expected browser CONTROLLER_MOVE rate (default: 30 Hz)",
    )
    args = parser.parse_args()
    if args.expected_hz <= 0:
        parser.error("--expected-hz must be greater than zero")

    with args.csv_file.open(newline="", encoding="utf-8") as source:
        rows = list(csv.DictReader(source))
    if not rows:
        raise SystemExit("CSV contains no samples")

    consumer_missing = 0
    duplicates = 0
    previous = None
    for row in rows:
        sequence = int(row["sequence"])
        if previous is not None:
            delta = sequence - previous
            if delta == 0:
                duplicates += 1
            elif delta > 1:
                consumer_missing += delta - 1
        previous = sequence

    # There is no browser-side sequence in the Vuer protocol. Estimate missing
    # 30 Hz source updates from gaps in browser timestamps. This represents
    # effective update loss (browser stall, queue drop, disconnect, or network),
    # not raw IP packet loss; WSS/TCP retransmits lost IP packets.
    expected_period_ns = 1_000_000_000 / args.expected_hz
    estimated_source_missing = 0
    previous_browser_ns = None
    for row in rows:
        browser_ns = int(row["browser_event_ns"])
        if previous_browser_ns is not None:
            delta_ns = browser_ns - previous_browser_ns
            if delta_ns > 0:
                elapsed_slots = max(1, round(delta_ns / expected_period_ns))
                estimated_source_missing += max(0, elapsed_slots - 1)
        previous_browser_ns = browser_ns

    consumer_expected = len(rows) + consumer_missing
    consumer_loss_percent = (
        100 * consumer_missing / consumer_expected if consumer_expected else 0.0
    )
    source_expected = len(rows) + estimated_source_missing
    source_loss_percent = (
        100 * estimated_source_missing / source_expected if source_expected else 0.0
    )

    print(f"samples={len(rows)} duplicates={duplicates}")
    print(
        f"consumer_missing_updates={consumer_missing} "
        f"consumer_loss={consumer_loss_percent:.3f}%"
    )
    print(
        f"estimated_end_to_end_missing_updates={estimated_source_missing} "
        f"estimated_end_to_end_loss={source_loss_percent:.3f}% "
        f"(expected_rate={args.expected_hz:g}Hz)"
    )
    print(
        "note: WSS uses TCP, so this is effective controller-update loss; "
        "it is not raw IP packet loss."
    )
    print("metric                         min      mean       p50       p95       p99       max")
    for metric in ("browser_to_xr_raw_ms", "browser_to_xr_ms"):
        values = [float(row[metric]) for row in rows if row.get(metric)]
        if not values:
            print(f"{metric:27s} unavailable (clock synchronization required)")
            continue
        print(
            f"{metric:27s} "
            f"{min(values):9.3f} {mean(values):9.3f} "
            f"{percentile(values, 50):9.3f} {percentile(values, 95):9.3f} "
            f"{percentile(values, 99):9.3f} {max(values):9.3f}"
        )


if __name__ == "__main__":
    main()
