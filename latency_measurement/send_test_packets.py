#!/usr/bin/env python3
"""Send synthetic timed packets without starting the XR/robot stack."""

from __future__ import annotations

import argparse
import secrets
import socket
import time

from clock_sync import estimate_udp_clock_offset
from latency_protocol import TimingPacket, pack_packet


def main():
    parser = argparse.ArgumentParser(description="Send synthetic XR timing packets")
    parser.add_argument("host", help="bridge host or VPN IP")
    parser.add_argument("--port", type=int, default=9870)
    parser.add_argument("--sync-port", type=int, default=9871)
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--hz", type=float, default=30.0)
    args = parser.parse_args()

    session_id = secrets.randbits(63)
    clock = estimate_udp_clock_offset(args.host, args.sync_port, sample_count=10)
    print(
        f"robot clock offset={clock.offset_ns / 1e6:.3f}ms "
        f"rtt={clock.rtt_ns / 1e6:.3f}ms"
    )
    period = 1.0 / args.hz
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        for sequence in range(1, args.count + 1):
            browser_event_ns = time.time_ns()
            xr_receive_ns = time.time_ns()
            packet = TimingPacket(
                session_id=session_id,
                sequence=sequence,
                browser_event_ns=browser_event_ns,
                xr_receive_ns=xr_receive_ns,
                xr_send_ns=time.time_ns(),
                browser_to_xr_offset_ns=0,
                xr_to_robot_offset_ns=clock.offset_ns,
                right_b=(sequence // 15) % 2 == 1,
                left_y=(sequence // 30) % 2 == 1,
            )
            sock.sendto(pack_packet(packet), (args.host, args.port))
            time.sleep(period)
    finally:
        sock.close()

    print(f"sent {args.count} packets, session={session_id}")


if __name__ == "__main__":
    main()
