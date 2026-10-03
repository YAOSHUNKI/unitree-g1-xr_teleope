"""NTP-style clock offset estimation used by the measurement tools."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import socket
import statistics
import struct
import time


SYNC_MAGIC = b"XCS1"
SYNC_VERSION = 1
SYNC_REQUEST_FORMAT = "<4sBQQ"       # magic, version, nonce, client t0
SYNC_RESPONSE_FORMAT = "<4sBQQQQ"    # magic, version, nonce, t0, server t1/t2
SYNC_REQUEST_SIZE = struct.calcsize(SYNC_REQUEST_FORMAT)
SYNC_RESPONSE_SIZE = struct.calcsize(SYNC_RESPONSE_FORMAT)


@dataclass(frozen=True)
class ClockSample:
    offset_ns: int
    rtt_ns: int


@dataclass(frozen=True)
class ClockEstimate:
    offset_ns: int
    rtt_ns: int
    successful_samples: int


def calculate_clock_sample(t0_ns: int, t1_ns: int, t2_ns: int, t3_ns: int) -> ClockSample:
    """Return server-minus-client offset and network RTT."""
    offset_ns = ((t1_ns - t0_ns) + (t2_ns - t3_ns)) // 2
    rtt_ns = (t3_ns - t0_ns) - (t2_ns - t1_ns)
    return ClockSample(offset_ns=offset_ns, rtt_ns=max(0, rtt_ns))


def select_clock_estimate(samples: list[ClockSample], best_count: int = 5) -> ClockEstimate:
    if not samples:
        raise ValueError("no successful clock samples")
    best = sorted(samples, key=lambda sample: sample.rtt_ns)[:max(1, best_count)]
    return ClockEstimate(
        offset_ns=int(statistics.median(sample.offset_ns for sample in best)),
        rtt_ns=int(statistics.median(sample.rtt_ns for sample in best)),
        successful_samples=len(samples),
    )


def estimate_udp_clock_offset(
    host: str,
    port: int,
    sample_count: int = 20,
    timeout_seconds: float = 0.25,
) -> ClockEstimate:
    """Estimate remote-server minus local-client clock offset over UDP."""
    samples: list[ClockSample] = []
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout_seconds)
    try:
        for nonce in range(1, sample_count + 1):
            t0_ns = time.time_ns()
            request = struct.pack(
                SYNC_REQUEST_FORMAT, SYNC_MAGIC, SYNC_VERSION, nonce, t0_ns
            )
            sock.sendto(request, (host, port))
            try:
                response, _ = sock.recvfrom(128)
                t3_ns = time.time_ns()
            except socket.timeout:
                continue
            if len(response) != SYNC_RESPONSE_SIZE:
                continue
            magic, version, reply_nonce, reply_t0_ns, t1_ns, t2_ns = struct.unpack(
                SYNC_RESPONSE_FORMAT, response
            )
            if (
                magic != SYNC_MAGIC
                or version != SYNC_VERSION
                or reply_nonce != nonce
                or reply_t0_ns != t0_ns
            ):
                continue
            samples.append(calculate_clock_sample(t0_ns, t1_ns, t2_ns, t3_ns))
            time.sleep(0.01)
    finally:
        sock.close()
    return select_clock_estimate(samples)


def make_sync_response(data: bytes, server_receive_ns: int) -> bytes:
    if len(data) != SYNC_REQUEST_SIZE:
        raise ValueError("invalid sync request size")
    magic, version, nonce, t0_ns = struct.unpack(SYNC_REQUEST_FORMAT, data)
    if magic != SYNC_MAGIC or version != SYNC_VERSION:
        raise ValueError("invalid sync request header")
    server_send_ns = time.time_ns()
    return struct.pack(
        SYNC_RESPONSE_FORMAT,
        SYNC_MAGIC,
        SYNC_VERSION,
        nonce,
        t0_ns,
        server_receive_ns,
        server_send_ns,
    )


def load_browser_clock_offset(path: Path, max_age_seconds: float = 600.0) -> ClockEstimate:
    data = json.loads(path.read_text(encoding="utf-8"))
    created_at_ns = int(data["created_at_ns"])
    age_seconds = (time.time_ns() - created_at_ns) / 1_000_000_000
    if age_seconds < -5 or age_seconds > max_age_seconds:
        raise ValueError(
            f"browser clock calibration is stale (age={age_seconds:.1f}s, "
            f"max={max_age_seconds:.1f}s)"
        )
    return ClockEstimate(
        offset_ns=int(data["offset_ns"]),
        rtt_ns=int(data["rtt_ns"]),
        successful_samples=int(data["successful_samples"]),
    )
