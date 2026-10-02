#!/usr/bin/env python3
"""
xr_button_bridge_node.py

Receive B/Y controller-button states from teleop_hand_and_arm_button.py over UDP
and republish them as ROS 2 std_msgs/Bool topics.

Payload (little-endian, 2 bytes total):
    '<??' = right_ctrl_bButton (B, right controller),
            left_ctrl_bButton  (Y, left controller — labeled Y on Meta Quest hardware)

Published topics:
    /teleop/button/right_b   std_msgs/Bool   True while B held, False otherwise
    /teleop/button/left_y    std_msgs/Bool   True while Y held, False otherwise

The node publishes the latest received state on a fixed timer (default 30 Hz),
so a subscriber sees continuous True while a button is held and continuous
False otherwise, independent of packet cadence. If no UDP packet has ever
arrived yet, it publishes False.
"""

import argparse
import socket
import struct
import sys

import rclpy
from rclpy.node import Node
from std_msgs.msg import Bool


FMT = '<??'
SIZE = struct.calcsize(FMT)


class XrButtonBridge(Node):
    def __init__(self, host: str, port: int, qos_depth: int, publish_hz: float):
        super().__init__('xr_button_bridge')

        self.pub_right_b = self.create_publisher(Bool, '/button_right', qos_depth)
        self.pub_left_y  = self.create_publisher(Bool, '/button_left',  qos_depth)

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((host, port))
        self.sock.setblocking(False)
        self.get_logger().info(
            f'listening on UDP {host}:{port} (payload fmt={FMT}, size={SIZE}), '
            f'publishing at {publish_hz:.1f} Hz'
        )

        self._right_b = False
        self._left_y = False

        # poll UDP fast; publish at requested rate
        self.create_timer(0.005, self._drain_udp)          # 200 Hz drain
        self.create_timer(1.0 / publish_hz, self._publish) # publish stream

    def _drain_udp(self):
        while True:
            try:
                data, _ = self.sock.recvfrom(64)
            except BlockingIOError:
                return
            except Exception as e:
                self.get_logger().warn(f'recvfrom failed: {e}')
                return
            if len(data) != SIZE:
                self.get_logger().warn(
                    f'ignoring packet of unexpected size {len(data)} (expected {SIZE})')
                continue
            right_b, left_y = struct.unpack(FMT, data)
            self._right_b = bool(right_b)
            self._left_y = bool(left_y)

    def _publish(self):
        self.pub_right_b.publish(Bool(data=self._right_b))
        self.pub_left_y.publish(Bool(data=self._left_y))

    def destroy_node(self):
        try:
            self.sock.close()
        except Exception:
            pass
        super().destroy_node()


def main(argv=None):
    parser = argparse.ArgumentParser(description='XR B/Y button UDP -> ROS 2 bridge')
    parser.add_argument('--host', type=str, default='0.0.0.0',
                        help='UDP bind host (0.0.0.0 = any interface, 127.0.0.1 = localhost only)')
    parser.add_argument('--port', type=int, default=9870, help='UDP bind port')
    parser.add_argument('--qos-depth', type=int, default=10, help='publisher QoS depth')
    parser.add_argument('--publish-hz', type=float, default=10.0,
                        help='rate at which to publish current state as Bool topics')
    args, ros_argv = parser.parse_known_args(argv if argv is not None else sys.argv[1:])

    rclpy.init(args=ros_argv)
    node = XrButtonBridge(host=args.host, port=args.port,
                          qos_depth=args.qos_depth, publish_hz=args.publish_hz)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        try:
            rclpy.shutdown()
        except Exception:
            pass


if __name__ == '__main__':
    main()