"""Wire format shared by the XR sender and robot-side bridge."""

from __future__ import annotations

import struct
from dataclasses import dataclass


MAGIC = b"XRT1"
VERSION = 1

# magic, version, session, sequence, browser event, XR receive, XR send,
# browser->XR clock offset, XR->robot clock offset, B, Y
PACKET_FORMAT = "<4sBQQQQQqq??"
PACKET_SIZE = struct.calcsize(PACKET_FORMAT)

# Int64MultiArray layout published by the ROS 2 bridge.
IDX_SESSION_ID = 0
IDX_SEQUENCE = 1
IDX_BROWSER_EVENT_NS = 2
IDX_BROWSER_TO_XR_OFFSET_NS = 3
IDX_XR_RECEIVE_NS = 4
IDX_XR_SEND_NS = 5
IDX_XR_TO_ROBOT_OFFSET_NS = 6
IDX_BRIDGE_RECEIVE_NS = 7
IDX_STATE = 8
TIMED_MESSAGE_LENGTH = 9


@dataclass(frozen=True)
class TimingPacket:
    session_id: int
    sequence: int
    browser_event_ns: int
    xr_receive_ns: int
    xr_send_ns: int
    browser_to_xr_offset_ns: int
    xr_to_robot_offset_ns: int
    right_b: bool
    left_y: bool


def pack_packet(packet: TimingPacket) -> bytes:
    return struct.pack(
        PACKET_FORMAT,
        MAGIC,
        VERSION,
        packet.session_id,
        packet.sequence,
        packet.browser_event_ns,
        packet.xr_receive_ns,
        packet.xr_send_ns,
        packet.browser_to_xr_offset_ns,
        packet.xr_to_robot_offset_ns,
        packet.right_b,
        packet.left_y,
    )


def unpack_packet(data: bytes) -> TimingPacket:
    if len(data) != PACKET_SIZE:
        raise ValueError(f"unexpected packet size {len(data)} (expected {PACKET_SIZE})")

    magic, version, *values = struct.unpack(PACKET_FORMAT, data)
    if magic != MAGIC:
        raise ValueError(f"unexpected magic {magic!r}")
    if version != VERSION:
        raise ValueError(f"unsupported protocol version {version}")

    return TimingPacket(*values)


def timed_message_data(packet: TimingPacket, bridge_receive_ns: int, state: bool) -> list[int]:
    return [
        packet.session_id,
        packet.sequence,
        packet.browser_event_ns,
        packet.browser_to_xr_offset_ns,
        packet.xr_receive_ns,
        packet.xr_send_ns,
        packet.xr_to_robot_offset_ns,
        bridge_receive_ns,
        int(state),
    ]
