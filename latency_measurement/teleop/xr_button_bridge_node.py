#!/usr/bin/env python3
"""Receive timed XR UDP packets and publish timed ROS 2 button messages."""

from __future__ import annotations

import argparse
import os
import socket
import sys
import time

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
MEASUREMENT_DIR = os.path.dirname(CURRENT_DIR)
sys.path.insert(0, MEASUREMENT_DIR)

import rclpy
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import Bool, Int64MultiArray

from clock_sync import make_sync_response
from latency_protocol import PACKET_SIZE, timed_message_data, unpack_packet


class TimedXrButtonBridge(Node):
    def __init__(self, host: str, port: int, sync_port: int, qos_depth: int):
        super().__init__("timed_xr_button_bridge")

        low_latency_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=qos_depth,
            reliability=ReliabilityPolicy.BEST_EFFORT,
        )
        self.pub_right_timed = self.create_publisher(
            Int64MultiArray, "/teleop/button/right_b_timed", low_latency_qos
        )
        self.pub_left_timed = self.create_publisher(
            Int64MultiArray, "/teleop/button/left_y_timed", low_latency_qos
        )

        # Compatibility topics for existing Bool subscribers.
        self.pub_right_bool = self.create_publisher(Bool, "/right_button", qos_depth)
        self.pub_left_bool = self.create_publisher(Bool, "/left_button", qos_depth)

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((host, port))
        self.sock.setblocking(False)

        self.sync_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sync_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sync_sock.bind((host, sync_port))
        self.sync_sock.setblocking(False)

        self._previous_session = None
        self._previous_sequence = None
        self._previous_right_b = False
        self._previous_left_y = False
        self._invalid_packets = 0

        self.get_logger().info(
            f"timed packets UDP {host}:{port}; clock sync UDP {host}:{sync_port}"
        )
        self.create_timer(0.001, self._poll)
        self.create_timer(0.001, self._poll_clock_sync)

    def _poll_clock_sync(self):
        while True:
            try:
                data, address = self.sync_sock.recvfrom(128)
                server_receive_ns = time.time_ns()
            except BlockingIOError:
                return
            except OSError as exc:
                self.get_logger().warning(f"clock sync recvfrom failed: {exc}")
                return
            try:
                response = make_sync_response(data, server_receive_ns)
                self.sync_sock.sendto(response, address)
            except (ValueError, OSError) as exc:
                self.get_logger().warning(f"ignored clock sync request: {exc}")

    def _poll(self):
        while True:
            try:
                data, address = self.sock.recvfrom(256)
                bridge_receive_ns = time.time_ns()
            except BlockingIOError:
                return
            except OSError as exc:
                self.get_logger().warning(f"recvfrom failed: {exc}")
                return

            try:
                packet = unpack_packet(data)
            except ValueError as exc:
                self._invalid_packets += 1
                if self._invalid_packets <= 5 or self._invalid_packets % 100 == 0:
                    self.get_logger().warning(f"ignored packet from {address}: {exc}")
                continue

            if packet.session_id != self._previous_session:
                self.get_logger().info(
                    f"new measurement session {packet.session_id} from {address}"
                )
                self._previous_session = packet.session_id
                self._previous_sequence = None

            if self._previous_sequence is not None and packet.sequence <= self._previous_sequence:
                self.get_logger().warning(
                    f"out-of-order/duplicate packet seq={packet.sequence}, "
                    f"previous={self._previous_sequence}"
                )
            self._previous_sequence = max(packet.sequence, self._previous_sequence or 0)

            right_msg = Int64MultiArray()
            right_msg.data = timed_message_data(packet, bridge_receive_ns, packet.right_b)
            self.pub_right_timed.publish(right_msg)

            left_msg = Int64MultiArray()
            left_msg.data = timed_message_data(packet, bridge_receive_ns, packet.left_y)
            self.pub_left_timed.publish(left_msg)

            if packet.right_b != self._previous_right_b:
                self.pub_right_bool.publish(Bool(data=packet.right_b))
                self._previous_right_b = packet.right_b

            if packet.left_y != self._previous_left_y:
                self.pub_left_bool.publish(Bool(data=packet.left_y))
                self._previous_left_y = packet.left_y

    def destroy_node(self):
        try:
            self.sock.close()
            self.sync_sock.close()
        finally:
            super().destroy_node()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Timed XR button UDP to ROS 2 bridge")
    parser.add_argument("--host", default="0.0.0.0", help="UDP bind address")
    parser.add_argument("--port", type=int, default=9870, help="UDP bind port")
    parser.add_argument("--sync-port", type=int, default=9871, help="clock sync UDP port")
    parser.add_argument("--qos-depth", type=int, default=10)
    args, ros_argv = parser.parse_known_args(argv if argv is not None else sys.argv[1:])

    rclpy.init(args=ros_argv)
    node = TimedXrButtonBridge(args.host, args.port, args.sync_port, args.qos_depth)
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
