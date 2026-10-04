#!/usr/bin/env python3
"""Create aligned latency and loss graphs from input and camera CSV logs."""

from __future__ import annotations

import argparse
import csv
import math
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from zoneinfo import ZoneInfo


_mpl_config = Path(tempfile.gettempdir()) / "xr_latency_matplotlib"
_mpl_config.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(_mpl_config))

try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except ImportError as exc:  # pragma: no cover - depends on the runtime environment
    raise SystemExit(
        "matplotlib is required to create graphs. Activate the existing tv environment "
        "that already provides matplotlib."
    ) from exc


INPUT_COLOR = "#2563EB"
CAMERA_COLOR = "#EA580C"
GRID_COLOR = "#D1D5DB"


@dataclass(frozen=True)
class InputSample:
    sequence: int
    browser_ms: float
    latency_ms: float | None
    right_b: int
    left_y: int


@dataclass(frozen=True)
class CameraSample:
    sequence: int
    browser_ms: float
    latency_ms: float


def percentile(values: list[float], percent: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * percent / 100
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def require_columns(path: Path, fieldnames: list[str] | None, required: set[str]) -> None:
    available = set(fieldnames or [])
    missing = sorted(required - available)
    if missing:
        raise SystemExit(f"{path}: missing required columns: {', '.join(missing)}")


def read_input_samples(path: Path, latency_column: str) -> list[InputSample]:
    required = {"sequence", "browser_event_ns", latency_column, "right_b", "left_y"}
    samples: list[InputSample] = []
    with path.open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        require_columns(path, reader.fieldnames, required)
        for row_number, row in enumerate(reader, start=2):
            try:
                latency_text = row[latency_column].strip()
                samples.append(
                    InputSample(
                        sequence=int(row["sequence"]),
                        browser_ms=int(row["browser_event_ns"]) / 1_000_000,
                        latency_ms=float(latency_text) if latency_text else None,
                        right_b=int(row["right_b"]),
                        left_y=int(row["left_y"]),
                    )
                )
            except (TypeError, ValueError) as exc:
                raise SystemExit(f"{path}:{row_number}: invalid input sample: {exc}") from exc
    if not samples:
        raise SystemExit(f"{path}: CSV contains no input samples")
    return sorted(samples, key=lambda sample: sample.browser_ms)


def read_camera_samples(path: Path) -> list[CameraSample]:
    required = {"sequence", "display_browser_ms", "latency_ms"}
    samples: list[CameraSample] = []
    with path.open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        require_columns(path, reader.fieldnames, required)
        for row_number, row in enumerate(reader, start=2):
            try:
                samples.append(
                    CameraSample(
                        sequence=int(row["sequence"]),
                        browser_ms=float(row["display_browser_ms"]),
                        latency_ms=float(row["latency_ms"]),
                    )
                )
            except (TypeError, ValueError) as exc:
                raise SystemExit(f"{path}:{row_number}: invalid camera sample: {exc}") from exc
    if not samples:
        raise SystemExit(f"{path}: CSV contains no camera samples")
    return sorted(samples, key=lambda sample: sample.browser_ms)


def parse_start_time(value: str, zone: ZoneInfo) -> float:
    try:
        return float(value) * 1000
    except ValueError:
        pass
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise SystemExit(
            "--start-time must be epoch seconds or ISO 8601, for example "
            "2026-10-04T15:30:00+09:00"
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=zone)
    return parsed.timestamp() * 1000


def select_start_ms(
    samples: list[InputSample], trigger: str, explicit_start: str | None, zone: ZoneInfo
) -> float:
    if explicit_start:
        return parse_start_time(explicit_start, zone)
    if trigger == "first":
        return samples[0].browser_ms
    previous = 0
    for sample in samples:
        current = sample.right_b if trigger == "right_b" else sample.left_y
        if current and not previous:
            return sample.browser_ms
        previous = current
    raise SystemExit(f"No rising edge for --trigger {trigger} was found in the input CSV")


def iso_time(epoch_ms: float, zone: ZoneInfo) -> str:
    return datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc).astimezone(zone).isoformat(
        timespec="milliseconds"
    )


def sequence_counts(sequences: list[int], wrap_32bit: bool) -> tuple[int, int]:
    missing = 0
    duplicates = 0
    for previous, current in zip(sequences, sequences[1:]):
        delta = (current - previous) & 0xFFFFFFFF if wrap_32bit else current - previous
        if delta == 0:
            duplicates += 1
        elif delta > 1 and (not wrap_32bit or delta < 0x80000000):
            missing += delta - 1
    return missing, duplicates


def estimated_input_missing(samples: list[InputSample], expected_hz: float) -> int:
    expected_period_ms = 1000 / expected_hz
    missing = 0
    for previous, current in zip(samples, samples[1:]):
        elapsed = current.browser_ms - previous.browser_ms
        if elapsed > 0:
            missing += max(0, round(elapsed / expected_period_ms) - 1)
    return missing


def latency_stats(values: list[float]) -> dict[str, float]:
    return {
        "min_ms": min(values),
        "mean_ms": mean(values),
        "p50_ms": percentile(values, 50),
        "p95_ms": percentile(values, 95),
        "p99_ms": percentile(values, 99),
        "max_ms": max(values),
    }


def downsample(points: list[tuple[float, float]], limit: int = 6000) -> list[tuple[float, float]]:
    if len(points) <= limit:
        return points
    step = math.ceil(len(points) / limit)
    return points[::step]


def style_axis(axis) -> None:
    axis.grid(True, color=GRID_COLOR, linewidth=0.7, alpha=0.65)
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)


def plot_timeline(
    input_samples: list[InputSample],
    camera_samples: list[CameraSample],
    start_ms: float,
    end_ms: float,
    start_label: str,
    output_path: Path,
) -> None:
    input_points = downsample(
        [
            ((sample.browser_ms - start_ms) / 1000, sample.latency_ms)
            for sample in input_samples
            if sample.latency_ms is not None
        ]
    )
    camera_points = downsample(
        [((sample.browser_ms - start_ms) / 1000, sample.latency_ms) for sample in camera_samples]
    )
    if not input_points:
        raise SystemExit("Input CSV has no synchronized browser_to_xr_ms values in the selected window")

    figure, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True, constrained_layout=True)
    figure.suptitle(f"Latency timeline\nStart: {start_label}", fontsize=14, fontweight="bold")

    for axis, points, color, title in (
        (axes[0], input_points, INPUT_COLOR, "Controller input latency"),
        (axes[1], camera_points, CAMERA_COLOR, "Camera display latency"),
    ):
        x_values = [point[0] for point in points]
        y_values = [point[1] for point in points]
        axis.plot(x_values, y_values, color=color, linewidth=0.8, alpha=0.75)
        axis.scatter(x_values, y_values, color=color, s=5, alpha=0.28, edgecolors="none")
        axis.axhline(percentile(y_values, 50), color=color, linestyle="--", linewidth=1.2, label="p50")
        axis.axhline(percentile(y_values, 95), color=color, linestyle=":", linewidth=1.4, label="p95")
        axis.set_title(title, loc="left", fontsize=11)
        axis.set_ylabel("Latency (ms)")
        axis.legend(loc="upper right", frameon=False, ncol=2)
        style_axis(axis)

    axes[1].set_xlabel("Seconds from common start")
    axes[1].set_xlim(0, max(0.001, (end_ms - start_ms) / 1000))
    figure.savefig(output_path, dpi=180, facecolor="white")
    plt.close(figure)


def plot_distribution(
    input_values: list[float], camera_values: list[float], output_path: Path
) -> None:
    figure, axes = plt.subplots(1, 2, figsize=(12, 4.8), constrained_layout=True)
    figure.suptitle("Latency distributions", fontsize=14, fontweight="bold")
    for axis, values, color, title in (
        (axes[0], input_values, INPUT_COLOR, "Controller input"),
        (axes[1], camera_values, CAMERA_COLOR, "Camera display"),
    ):
        bins = min(60, max(12, round(math.sqrt(len(values)))))
        axis.hist(values, bins=bins, color=color, alpha=0.78, edgecolor="white", linewidth=0.5)
        for percent, style in ((50, "--"), (95, ":"), (99, "-.")):
            value = percentile(values, percent)
            axis.axvline(value, color="#111827", linestyle=style, linewidth=1.2, label=f"p{percent}={value:.1f} ms")
        axis.set_title(title, loc="left", fontsize=11)
        axis.set_xlabel("Latency (ms)")
        axis.set_ylabel("Samples")
        axis.legend(frameon=False, fontsize=9)
        style_axis(axis)
    figure.savefig(output_path, dpi=180, facecolor="white")
    plt.close(figure)


def loss_bins(
    timestamps_ms: list[float],
    sequences: list[int],
    start_ms: float,
    duration_seconds: float,
    bin_seconds: float,
    expected_hz: float | None,
    wrap_32bit: bool,
) -> tuple[list[float], list[float]]:
    bin_count = max(1, math.ceil(duration_seconds / bin_seconds))
    received = [0] * bin_count
    missing = [0] * bin_count
    for timestamp in timestamps_ms:
        index = min(bin_count - 1, max(0, int((timestamp - start_ms) / 1000 / bin_seconds)))
        received[index] += 1
    for index_in_samples in range(1, len(timestamps_ms)):
        if expected_hz is not None:
            elapsed = timestamps_ms[index_in_samples] - timestamps_ms[index_in_samples - 1]
            lost = max(0, round(elapsed / (1000 / expected_hz)) - 1) if elapsed > 0 else 0
        else:
            delta = sequences[index_in_samples] - sequences[index_in_samples - 1]
            if wrap_32bit:
                delta &= 0xFFFFFFFF
            lost = delta - 1 if delta > 1 and (not wrap_32bit or delta < 0x80000000) else 0
        if lost:
            bin_index = min(
                bin_count - 1,
                max(0, int((timestamps_ms[index_in_samples] - start_ms) / 1000 / bin_seconds)),
            )
            missing[bin_index] += lost
    centers = [(index + 0.5) * bin_seconds for index in range(bin_count)]
    rates = [
        100 * lost / (count + lost) if count + lost else math.nan
        for count, lost in zip(received, missing)
    ]
    return centers, rates


def plot_loss(
    input_samples: list[InputSample],
    camera_samples: list[CameraSample],
    start_ms: float,
    duration_seconds: float,
    bin_seconds: float,
    expected_hz: float,
    output_path: Path,
) -> None:
    input_x, input_rates = loss_bins(
        [sample.browser_ms for sample in input_samples],
        [sample.sequence for sample in input_samples],
        start_ms,
        duration_seconds,
        bin_seconds,
        expected_hz,
        False,
    )
    camera_x, camera_rates = loss_bins(
        [sample.browser_ms for sample in camera_samples],
        [sample.sequence for sample in camera_samples],
        start_ms,
        duration_seconds,
        bin_seconds,
        None,
        True,
    )
    figure, axis = plt.subplots(figsize=(12, 4.8), constrained_layout=True)
    axis.step(
        input_x,
        input_rates,
        where="mid",
        color=INPUT_COLOR,
        linewidth=1.5,
        label="Controller updates",
        zorder=4,
    )
    axis.step(
        camera_x,
        camera_rates,
        where="mid",
        color=CAMERA_COLOR,
        linewidth=1.5,
        label="Camera frames",
        zorder=4,
    )
    axis.set_title(f"Effective loss by {bin_seconds:g}-second interval", loc="left", fontsize=14, fontweight="bold")
    axis.set_xlabel("Seconds from common start")
    axis.set_ylabel("Loss (%)")
    axis.set_xlim(0, max(0.001, duration_seconds))
    axis.set_ylim(bottom=0)
    axis.legend(loc="upper right", frameon=False, ncol=2)
    style_axis(axis)
    figure.savefig(output_path, dpi=180, facecolor="white")
    plt.close(figure)


def write_summary(
    output_path: Path,
    input_samples: list[InputSample],
    camera_samples: list[CameraSample],
    expected_hz: float,
    start_label: str,
    end_label: str,
    duration_seconds: float,
) -> None:
    input_values = [sample.latency_ms for sample in input_samples if sample.latency_ms is not None]
    camera_values = [sample.latency_ms for sample in camera_samples]
    if not input_values:
        raise SystemExit("Input CSV has no synchronized browser_to_xr_ms values in the selected window")

    input_missing = estimated_input_missing(input_samples, expected_hz)
    input_consumer_missing, input_duplicates = sequence_counts(
        [sample.sequence for sample in input_samples], False
    )
    camera_missing, camera_duplicates = sequence_counts(
        [sample.sequence for sample in camera_samples], True
    )
    rows = []
    for stream, values, samples, missing, duplicates, consumer_missing in (
        (
            "controller_input",
            input_values,
            len(input_samples),
            input_missing,
            input_duplicates,
            input_consumer_missing,
        ),
        (
            "camera_display",
            camera_values,
            len(camera_samples),
            camera_missing,
            camera_duplicates,
            "",
        ),
    ):
        stats = latency_stats(values)
        expected = samples + missing
        rows.append(
            {
                "stream": stream,
                "start_time": start_label,
                "end_time": end_label,
                "duration_s": f"{duration_seconds:.3f}",
                "samples": samples,
                "missing": missing,
                "duplicates": duplicates,
                "loss_percent": f"{100 * missing / expected if expected else 0:.6f}",
                "consumer_missing": consumer_missing,
                **{key: f"{value:.6f}" for key, value in stats.items()},
            }
        )
    fieldnames = [
        "stream",
        "start_time",
        "end_time",
        "duration_s",
        "samples",
        "missing",
        "duplicates",
        "loss_percent",
        "consumer_missing",
        "min_ms",
        "mean_ms",
        "p50_ms",
        "p95_ms",
        "p99_ms",
        "max_ms",
    ]
    with output_path.open("w", newline="", encoding="utf-8") as destination:
        writer = csv.DictWriter(destination, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create aligned input/camera latency and effective-loss graphs"
    )
    parser.add_argument("input_csv", type=Path, help="XR input latency CSV")
    parser.add_argument("camera_csv", type=Path, help="Camera latency CSV")
    parser.add_argument("--output-dir", type=Path, help="Output directory")
    parser.add_argument(
        "--trigger",
        choices=("first", "right_b", "left_y"),
        default="first",
        help="Common start marker from input CSV (default: first)",
    )
    parser.add_argument(
        "--start-time",
        help="Override start with epoch seconds or ISO 8601; naive ISO uses --timezone",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=90.0,
        help="Measurement window in seconds (default: 90)",
    )
    parser.add_argument("--expected-hz", type=float, default=30.0)
    parser.add_argument("--loss-bin-seconds", type=float, default=1.0)
    parser.add_argument("--timezone", default="Asia/Tokyo")
    parser.add_argument(
        "--input-latency-column",
        choices=("browser_to_xr_ms", "browser_to_xr_raw_ms"),
        default="browser_to_xr_ms",
        help="Input latency metric to graph (default: clock-corrected browser_to_xr_ms)",
    )
    args = parser.parse_args()

    if args.expected_hz <= 0:
        parser.error("--expected-hz must be greater than zero")
    if args.duration <= 0:
        parser.error("--duration must be greater than zero")
    if args.loss_bin_seconds <= 0:
        parser.error("--loss-bin-seconds must be greater than zero")
    try:
        zone = ZoneInfo(args.timezone)
    except Exception as exc:
        parser.error(f"invalid --timezone: {exc}")

    input_samples_all = read_input_samples(args.input_csv, args.input_latency_column)
    camera_samples_all = read_camera_samples(args.camera_csv)
    start_ms = select_start_ms(input_samples_all, args.trigger, args.start_time, zone)
    end_ms = start_ms + args.duration * 1000
    available_end_ms = min(input_samples_all[-1].browser_ms, camera_samples_all[-1].browser_ms)
    end_tolerance_ms = max(250.0, 1000 / args.expected_hz * 2)
    if available_end_ms < end_ms - end_tolerance_ms:
        available_seconds = max(0.0, (available_end_ms - start_ms) / 1000)
        raise SystemExit(
            f"The common data window is only {available_seconds:.3f} seconds; "
            f"{args.duration:g} seconds are required"
        )
    input_samples = [sample for sample in input_samples_all if start_ms <= sample.browser_ms <= end_ms]
    camera_samples = [sample for sample in camera_samples_all if start_ms <= sample.browser_ms <= end_ms]
    if len(input_samples) < 2:
        raise SystemExit("Fewer than two input samples exist in the selected window")
    if len(camera_samples) < 2:
        raise SystemExit("Fewer than two camera samples exist in the selected window")

    output_dir = args.output_dir or args.input_csv.parent / f"{args.input_csv.stem}_graphs"
    output_dir.mkdir(parents=True, exist_ok=True)
    start_label = iso_time(start_ms, zone)
    end_label = iso_time(end_ms, zone)
    duration_seconds = (end_ms - start_ms) / 1000

    input_values = [sample.latency_ms for sample in input_samples if sample.latency_ms is not None]
    camera_values = [sample.latency_ms for sample in camera_samples]
    if not input_values:
        raise SystemExit("Input CSV has no synchronized browser_to_xr_ms values in the selected window")

    outputs = {
        "timeline": output_dir / "latency_timeline.png",
        "distribution": output_dir / "latency_distribution.png",
        "loss": output_dir / "loss_timeline.png",
        "summary": output_dir / "latency_summary.csv",
    }
    plot_timeline(input_samples, camera_samples, start_ms, end_ms, start_label, outputs["timeline"])
    plot_distribution(input_values, camera_values, outputs["distribution"])
    plot_loss(
        input_samples,
        camera_samples,
        start_ms,
        duration_seconds,
        args.loss_bin_seconds,
        args.expected_hz,
        outputs["loss"],
    )
    write_summary(
        outputs["summary"],
        input_samples,
        camera_samples,
        args.expected_hz,
        start_label,
        end_label,
        duration_seconds,
    )

    print(f"common_start={start_label}")
    print(f"common_end={end_label}")
    print(f"duration_s={duration_seconds:.3f}")
    for label, path in outputs.items():
        print(f"{label}={path}")


if __name__ == "__main__":
    main()
