#!/usr/bin/env python3
"""Standalone Docker-side camera latency launcher and CSV analyzer.

Only this file needs to be copied into a container that already has the normal
``teleimager`` image server and its dependencies installed.  In server mode it
patches teleimager in memory; it never imports another file from this project.
"""

from __future__ import annotations

import argparse
import csv
import math
import os
from pathlib import Path
import sys
import time
from statistics import mean
from typing import Any


MARKER_MAGIC = b"\xA5\x5A"
MARKER_CELL_SIZE = 8
MARKER_ROWS = 2
MARKER_COLUMNS = 56
MARKER_BYTES = 14


def _checksum(data: bytes) -> int:
    value = 0
    for byte in data:
        value ^= byte
    return value


def encode_marker(frame: Any, timestamp_ns: int, sequence: int) -> Any:
    """Place a codec-resistant 112-bit timestamp marker in a BGR frame."""
    if frame is None or getattr(frame, "ndim", 0) != 3:
        return frame
    width = MARKER_COLUMNS * MARKER_CELL_SIZE
    height = MARKER_ROWS * MARKER_CELL_SIZE
    if frame.shape[1] < width or frame.shape[0] < height:
        return frame

    timestamp_us = (timestamp_ns // 1_000) & ((1 << 56) - 1)
    body = (
        MARKER_MAGIC
        + timestamp_us.to_bytes(7, "big")
        + (sequence & 0xFFFFFFFF).to_bytes(4, "big")
    )
    payload = body + bytes([_checksum(body)])
    marked = frame.copy()
    for bit_index in range(MARKER_BYTES * 8):
        bit = (payload[bit_index // 8] >> (7 - bit_index % 8)) & 1
        row, column = divmod(bit_index, MARKER_COLUMNS)
        x0 = column * MARKER_CELL_SIZE
        y0 = row * MARKER_CELL_SIZE
        marked[y0:y0 + MARKER_CELL_SIZE, x0:x0 + MARKER_CELL_SIZE] = 255 if bit else 0
    return marked


def _percentile(values: list[float], percent: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * percent / 100
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def analyze_csv(csv_path: Path) -> None:
    """Print latency statistics without importing teleimager."""
    with csv_path.open(newline="", encoding="utf-8") as csv_file:
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
        f"p50={_percentile(values, 50):.3f} "
        f"p95={_percentile(values, 95):.3f} "
        f"p99={_percentile(values, 99):.3f} max={max(values):.3f}"
    )


HTML_FRAGMENT = """
<canvas id="latency-canvas" style="display:none"></canvas>
<div id="latency" style="font:18px monospace;white-space:pre-wrap;margin:12px">
  カメラ遅延計測: 初期化中
</div>
"""


# This add-on deliberately uses only endpoints installed below.  It wraps the
# stock teleimager start()/stop() functions instead of replacing its WebRTC UI.
CLIENT_ADDON = r"""

var latencyConfig = null;
var robotMinusBrowserMs = 0;
var latencyValues = [];
var latencyBatch = [];
var lastLatencySequence = null;
var latencyCallbackStarted = false;

const latencyEpochMs = () => performance.timeOrigin + performance.now();
const latencySleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));

async function latencyPrepare() {
    latencyConfig = await fetch('/latency-config', {cache: 'no-store'}).then(r => r.json());
    var status = document.getElementById('latency');
    var samples = [];
    for (var nonce = 1; nonce <= 20; nonce++) {
        var t0 = latencyEpochMs();
        var reply = await fetch('/latency-sync', {
            method: 'POST', cache: 'no-store',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({nonce: nonce})
        }).then(r => r.json());
        var t3 = latencyEpochMs();
        samples.push({
            offset: ((reply.t1_ms - t0) + (reply.t2_ms - t3)) / 2,
            rtt: Math.max(0, (t3 - t0) - (reply.t2_ms - reply.t1_ms))
        });
        status.textContent = `時計同期中 ${nonce}/20`;
        await latencySleep(20);
    }
    samples.sort((a, b) => a.rtt - b.rtt);
    var best = samples.slice(0, 5).sort((a, b) => a.offset - b.offset);
    robotMinusBrowserMs = best[Math.floor(best.length / 2)].offset;
    status.textContent = `時計同期完了 offset=${robotMinusBrowserMs.toFixed(3)} ms`;
}

function latencyDecode(video) {
    if (!latencyConfig || video.videoWidth < latencyConfig.width ||
        video.videoHeight < latencyConfig.height) return null;
    var canvas = document.getElementById('latency-canvas');
    canvas.width = latencyConfig.width;
    canvas.height = latencyConfig.height;
    var context = canvas.getContext('2d', {willReadFrequently: true});
    context.drawImage(video, 0, 0, canvas.width, canvas.height,
                      0, 0, canvas.width, canvas.height);
    var pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
    var bytes = new Uint8Array(14);
    for (var bitIndex = 0; bitIndex < 112; bitIndex++) {
        var row = Math.floor(bitIndex / latencyConfig.columns);
        var column = bitIndex % latencyConfig.columns;
        var x = Math.floor((column + 0.5) * latencyConfig.cell_size);
        var y = Math.floor((row + 0.5) * latencyConfig.cell_size);
        var pixel = (y * canvas.width + x) * 4;
        var light = (pixels[pixel] + pixels[pixel + 1] + pixels[pixel + 2]) / 3;
        if (light > 127) bytes[Math.floor(bitIndex / 8)] |= 1 << (7 - bitIndex % 8);
    }
    if (bytes[0] !== 0xA5 || bytes[1] !== 0x5A) return null;
    var check = 0;
    for (var i = 0; i < 13; i++) check ^= bytes[i];
    if (check !== bytes[13]) return null;
    var captureUs = 0;
    for (var i = 2; i < 9; i++) captureUs = captureUs * 256 + bytes[i];
    var sequence = 0;
    for (var i = 9; i < 13; i++) sequence = sequence * 256 + bytes[i];
    return {capture_us: captureUs, sequence: sequence};
}

function latencyPercentile(values, fraction) {
    var ordered = [...values].sort((a, b) => a - b);
    return ordered[Math.floor((ordered.length - 1) * fraction)];
}

function latencyStartFrames() {
    if (latencyCallbackStarted) return;
    var video = document.getElementById('video');
    if (!video || !video.requestVideoFrameCallback || video.readyState < 2) {
        setTimeout(latencyStartFrames, 100);
        return;
    }
    latencyCallbackStarted = true;
    var onFrame = (now) => {
        var marker = latencyDecode(video);
        if (marker && marker.sequence !== lastLatencySequence) {
            lastLatencySequence = marker.sequence;
            var displayMs = performance.timeOrigin + now;
            var latencyMs = displayMs + robotMinusBrowserMs - marker.capture_us / 1000;
            latencyValues.push(latencyMs);
            if (latencyValues.length > 300) latencyValues.shift();
            latencyBatch.push({
                sequence: marker.sequence,
                capture_us: String(marker.capture_us),
                display_browser_ms: displayMs,
                robot_minus_browser_ms: robotMinusBrowserMs,
                latency_ms: latencyMs
            });
            document.getElementById('latency').textContent =
                `カメラ遅延 ${latencyMs.toFixed(1)} ms  ` +
                `p50=${latencyPercentile(latencyValues, .50).toFixed(1)}  ` +
                `p95=${latencyPercentile(latencyValues, .95).toFixed(1)}  ` +
                `frames=${latencyValues.length}`;
            if (latencyBatch.length >= 30) latencyFlush(false);
        }
        video.requestVideoFrameCallback(onFrame);
    };
    video.requestVideoFrameCallback(onFrame);
}

function latencyFlush(beacon) {
    if (!latencyBatch.length) return;
    var body = JSON.stringify({samples: latencyBatch});
    latencyBatch = [];
    if (beacon) navigator.sendBeacon('/latency-result',
        new Blob([body], {type: 'application/json'}));
    else fetch('/latency-result', {method: 'POST',
        headers: {'Content-Type': 'application/json'}, body: body}).catch(() => {});
}

const teleimagerStart = start;
start = async function() {
    await latencyPrepare();
    teleimagerStart();
    latencyStartFrames();
};
const teleimagerStop = stop;
stop = function() {
    latencyFlush(true);
    teleimagerStop();
};
window.addEventListener('pagehide', () => latencyFlush(true));
"""


def install_runtime_patch(log_dir: Path):
    """Import the container's teleimager and add the probe in memory."""
    try:
        import teleimager.image_server as server
    except ImportError as exc:
        raise SystemExit(
            "teleimager.image_serverをimportできません。通常の画像サーバーが動く"
            "Docker環境でこのファイルを実行してください。\n" + str(exc)
        ) from exc

    # A measurement-enabled copied teleimager already contains all patches.
    # Setting the environment before this import activates that implementation.
    if hasattr(server, "LATENCY_MARKER_MAGIC"):
        return server

    if "latency-canvas" not in server.INDEX_HTML:
        server.INDEX_HTML = server.INDEX_HTML.replace(
            "</body>", HTML_FRAGMENT + "\n</body>"
        )
    server.CLIENT_JS += CLIENT_ADDON

    publisher_class = server.WebRTC_PublisherThread
    original_init = publisher_class.__init__

    async def latency_config(self, request):
        return server.web.json_response({
            "enabled": True,
            "cell_size": MARKER_CELL_SIZE,
            "rows": MARKER_ROWS,
            "columns": MARKER_COLUMNS,
            "width": MARKER_COLUMNS * MARKER_CELL_SIZE,
            "height": MARKER_ROWS * MARKER_CELL_SIZE,
        })

    async def latency_sync(self, request):
        receive_ns = time.time_ns()
        try:
            payload = await request.json()
            nonce = int(payload.get("nonce", 0))
        except Exception:
            return server.web.json_response({"error": "invalid request"}, status=400)
        return server.web.json_response({
            "nonce": nonce,
            "t1_ms": receive_ns / 1_000_000,
            "t2_ms": time.time_ns() / 1_000_000,
        })

    async def latency_result(self, request):
        try:
            payload = await request.json()
            samples = payload.get("samples", [])
            if not isinstance(samples, list) or len(samples) > 300:
                raise ValueError("invalid samples")
            self._latency_log_path.parent.mkdir(parents=True, exist_ok=True)
            write_header = (
                not self._latency_log_path.exists()
                or self._latency_log_path.stat().st_size == 0
            )
            fields = [
                "received_ns", "client", "webrtc_port", "sequence", "capture_us",
                "display_browser_ms", "robot_minus_browser_ms", "latency_ms",
            ]
            with self._latency_log_path.open("a", newline="", encoding="utf-8") as output:
                writer = csv.DictWriter(output, fieldnames=fields)
                if write_header:
                    writer.writeheader()
                for sample in samples:
                    writer.writerow({
                        "received_ns": time.time_ns(),
                        "client": request.remote or "",
                        "webrtc_port": self._port,
                        "sequence": int(sample["sequence"]),
                        "capture_us": int(sample["capture_us"]),
                        "display_browser_ms": f'{float(sample["display_browser_ms"]):.6f}',
                        "robot_minus_browser_ms": f'{float(sample["robot_minus_browser_ms"]):.6f}',
                        "latency_ms": f'{float(sample["latency_ms"]):.6f}',
                    })
            return server.web.json_response({"saved": len(samples)})
        except (KeyError, TypeError, ValueError) as exc:
            return server.web.json_response({"error": str(exc)}, status=400)

    publisher_class._latency_config = latency_config
    publisher_class._latency_sync = latency_sync
    publisher_class._latency_result = latency_result

    def patched_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self._latency_log_path = log_dir / f"xr_camera_latency_{self._port}.csv"
        self._app.router.add_get("/latency-config", self._latency_config)
        self._app.router.add_post("/latency-sync", self._latency_sync)
        self._app.router.add_post("/latency-result", self._latency_result)
        print(f"[Camera Latency] CSV={self._latency_log_path}", flush=True)

    publisher_class.__init__ = patched_init

    manager_class = server.WebRTC_PublisherManager
    original_publish = manager_class.publish
    sequences: dict[int, int] = {}

    def patched_publish(self, data, port, host="0.0.0.0", codec_pref=None):
        sequence = sequences.get(port, 0)
        sequences[port] = (sequence + 1) & 0xFFFFFFFF
        marked = encode_marker(data, time.time_ns(), sequence)
        return original_publish(self, marked, port, host, codec_pref)

    manager_class.publish = patched_publish
    return server


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Standalone teleimager camera-latency launcher / CSV analyzer",
        add_help=False,
    )
    parser.add_argument("--analyze", type=Path, metavar="CSV")
    parser.add_argument("--latency-log-dir", type=Path, default=Path("/tmp"))
    parser.add_argument("--latency-help", action="store_true")
    options, teleimager_args = parser.parse_known_args()

    if options.latency_help:
        print("独自引数: --latency-log-dir DIR | --analyze CSV | --latency-help")
        print("その他の引数（例: --rs）はteleimager.image_serverへ渡します。")
        return
    if options.analyze is not None:
        analyze_csv(options.analyze)
        return

    options.latency_log_dir = options.latency_log_dir.resolve()
    os.environ["XR_CAMERA_LATENCY_PROBE"] = "1"
    os.environ["XR_CAMERA_LATENCY_LOG_DIR"] = str(options.latency_log_dir)
    server = install_runtime_patch(options.latency_log_dir)
    sys.argv = [sys.argv[0], *teleimager_args]
    server.main()


if __name__ == "__main__":
    main()
