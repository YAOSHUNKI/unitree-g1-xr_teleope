#!/usr/bin/env python3
"""ROS 2 subscriber that records XR-to-robot latency samples as CSV."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
import os
from pathlib import Path
import sys
import time

CURRENT_DIR = Path(__file__).resolve().parent
MEASUREMENT_DIR = CURRENT_DIR.parent
sys.path.insert(0, str(MEASUREMENT_DIR))

import rclpy
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import Int64MultiArray

from latency_protocol import (
    IDX_BRIDGE_RECEIVE_NS,
    IDX_BROWSER_EVENT_NS,
    IDX_BROWSER_TO_XR_OFFSET_NS,
    IDX_SEQUENCE,
    IDX_SESSION_ID,
    IDX_STATE,
    IDX_XR_RECEIVE_NS,
    IDX_XR_SEND_NS,
    IDX_XR_TO_ROBOT_OFFSET_NS,
    TIMED_MESSAGE_LENGTH,
)


CSV_FIELDS = [
    "received_iso",
    "topic",
    "session_id",
    "sequence",
    "state",
    "sequence_gap",
    "browser_event_ns",
    "browser_to_xr_offset_ns",
    "xr_receive_ns",
    "xr_send_ns",
    "xr_to_robot_offset_ns",
    "bridge_receive_ns",
    "subscriber_receive_ns",
    "browser_to_xr_raw_ms",
    "browser_to_xr_ms",
    "xr_processing_ms",
    "wan_ms",
    "wan_raw_ms",
    "ros_delivery_ms",
    "end_to_end_ms",
    "end_to_end_raw_ms",
]


class TimedButtonSubscriber(Node):
    def __init__(self, output_path: Path, qos_depth: int, log_every: int):
        super().__init__("timed_button_latency_subscriber")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        self._file = output_path.open("w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._file, fieldnames=CSV_FIELDS)
        self._writer.writeheader()

        self._log_every = max(1, log_every)
        self._sample_count = 0
        self._previous: dict[str, tuple[int, int]] = {}
        self._previous_state: dict[str, bool] = {}

        qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=qos_depth,
            reliability=ReliabilityPolicy.BEST_EFFORT,
        )
        self.create_subscription(
            Int64MultiArray,
            "/teleop/button/right_b_timed",
            lambda msg: self._callback("right_b", msg),
            qos,
        )
        self.create_subscription(
            Int64MultiArray,
            "/teleop/button/left_y_timed",
            lambda msg: self._callback("left_y", msg),
            qos,
        )
        self.get_logger().info(f"writing latency samples to {output_path}")

    def _callback(self, topic: str, msg: Int64MultiArray):
        subscriber_receive_ns = time.time_ns()
        if len(msg.data) != TIMED_MESSAGE_LENGTH:
            self.get_logger().warning(
                f"ignored {topic} message with {len(msg.data)} fields; "
                f"expected {TIMED_MESSAGE_LENGTH}"
            )
            return

        session_id = int(msg.data[IDX_SESSION_ID])
        sequence = int(msg.data[IDX_SEQUENCE])
        browser_event_ns = int(msg.data[IDX_BROWSER_EVENT_NS])
        browser_to_xr_offset_ns = int(msg.data[IDX_BROWSER_TO_XR_OFFSET_NS])
        xr_receive_ns = int(msg.data[IDX_XR_RECEIVE_NS])
        xr_send_ns = int(msg.data[IDX_XR_SEND_NS])
        xr_to_robot_offset_ns = int(msg.data[IDX_XR_TO_ROBOT_OFFSET_NS])
        bridge_receive_ns = int(msg.data[IDX_BRIDGE_RECEIVE_NS])
        state = bool(msg.data[IDX_STATE])

        previous = self._previous.get(topic)
        sequence_gap = 0
        if previous is not None and previous[0] == session_id:
            sequence_gap = max(0, sequence - previous[1] - 1)
        self._previous[topic] = (session_id, sequence)

        browser_event_xr_ns = browser_event_ns + browser_to_xr_offset_ns
        xr_send_robot_ns = xr_send_ns + xr_to_robot_offset_ns
        browser_event_robot_ns = browser_event_xr_ns + xr_to_robot_offset_ns

        browser_to_xr_raw_ms = (xr_receive_ns - browser_event_ns) / 1_000_000
        browser_to_xr_ms = (xr_receive_ns - browser_event_xr_ns) / 1_000_000
        xr_processing_ms = (xr_send_ns - xr_receive_ns) / 1_000_000
        wan_raw_ms = (bridge_receive_ns - xr_send_ns) / 1_000_000
        wan_ms = (bridge_receive_ns - xr_send_robot_ns) / 1_000_000
        ros_delivery_ms = (subscriber_receive_ns - bridge_receive_ns) / 1_000_000
        end_to_end_raw_ms = (subscriber_receive_ns - browser_event_ns) / 1_000_000
        end_to_end_ms = (subscriber_receive_ns - browser_event_robot_ns) / 1_000_000

        self._writer.writerow(
            {
                "received_iso": datetime.now().astimezone().isoformat(),
                "topic": topic,
                "session_id": session_id,
                "sequence": sequence,
                "state": int(state),
                "sequence_gap": sequence_gap,
                "browser_event_ns": browser_event_ns,
                "browser_to_xr_offset_ns": browser_to_xr_offset_ns,
                "xr_receive_ns": xr_receive_ns,
                "xr_send_ns": xr_send_ns,
                "xr_to_robot_offset_ns": xr_to_robot_offset_ns,
                "bridge_receive_ns": bridge_receive_ns,
                "subscriber_receive_ns": subscriber_receive_ns,
                "browser_to_xr_raw_ms": f"{browser_to_xr_raw_ms:.6f}",
                "browser_to_xr_ms": f"{browser_to_xr_ms:.6f}",
                "xr_processing_ms": f"{xr_processing_ms:.6f}",
                "wan_ms": f"{wan_ms:.6f}",
                "wan_raw_ms": f"{wan_raw_ms:.6f}",
                "ros_delivery_ms": f"{ros_delivery_ms:.6f}",
                "end_to_end_ms": f"{end_to_end_ms:.6f}",
                "end_to_end_raw_ms": f"{end_to_end_raw_ms:.6f}",
            }
        )
        self._sample_count += 1
        if self._sample_count % self._log_every == 0:
            self._file.flush()

        changed = self._previous_state.get(topic) != state
        self._previous_state[topic] = state
        if changed or self._sample_count % self._log_every == 0 or sequence_gap:
            self.get_logger().info(
                f"{topic} seq={sequence} state={int(state)} gap={sequence_gap} "
                f"e2e={end_to_end_ms:.2f}ms wan={wan_ms:.2f}ms "
                f"ros={ros_delivery_ms:.2f}ms"
            )

    def destroy_node(self):
        try:
            self._file.flush()
            self._file.close()
        finally:
            super().destroy_node()


def default_output_path() -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path("logs") / f"xr_latency_{timestamp}.csv"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Record timed XR button ROS messages")
    parser.add_argument("--output", type=Path, default=default_output_path())
    parser.add_argument("--qos-depth", type=int, default=10)
    parser.add_argument("--log-every", type=int, default=30)
    args, ros_argv = parser.parse_known_args(argv if argv is not None else sys.argv[1:])

    rclpy.init(args=ros_argv)
    node = TimedButtonSubscriber(args.output, args.qos_depth, args.log_every)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
