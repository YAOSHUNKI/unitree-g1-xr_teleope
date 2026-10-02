#!/usr/bin/env python3
"""
xr_button_bridge_node.py

Receive B/Y controller-button states from teleop_hand_and_arm_button.py over UDP
and republish them as ROS 2 std_msgs/Bool edge events.

Payload (little-endian, 2 bytes total):
    '<??' = right_ctrl_bButton (B, right controller),
            left_ctrl_bButton  (Y, left controller — labeled Y on Meta Quest hardware)

Published topics (edge-triggered):
    /teleop/button/right_b   std_msgs/Bool   True once on press, False once on release
    /teleop/button/left_y    std_msgs/Bool   True once on press, False once on release
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
    def __init__(self, host: str, port: int, qos_depth: int):
        super().__init__('xr_button_bridge')

        self.pub_right_b = self.create_publisher(Bool, '/right_button', qos_depth)
        self.pub_left_y  = self.create_publisher(Bool, '/left_button',  qos_depth)

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_






































































































































                             
                             
                             
                             
                             
                             
                             
                             
                             
                             
                             
                             
                             
                             
                             
                             
                             
                             
                             
                             
                             
                             
                             
                             
                             
                             
                             
                             
                             
                             
                             
                             
                             
                             
                             
                             
                             
                             
                             
                             
























































                             
                             
                             
                             
                             
                             
                             
                             
                             
                             
                             
                             
                             
                             
                             
                             
                             
                             
                             
                             
                             
                             
                             
                             
                             
                             
                             
                             
                             
                             
                             
                             











































                             REUSEADDR, 1)
        self.sock.bind((host, port))
        self.sock.setblocking(False)
        self.get_logger().info(
            f'listening on UDP {host}:{port} (payload fmt={FMT}, size={SIZE}) - edge mode'
        )

        # previous states for edge detection
        self._prev_right_b = False
        self._prev_left_y = False

        # poll UDP at 200 Hz; publish only on state change
        self.create_timer(0.005, self._poll)

    def _poll(self):
        latest = None
        while True:
            try:
                data, _ = self.sock.recvfrom(64)
            except BlockingIOError:
                break
            except Exception as e:
                self.get_logger().warn(f'recvfrom failed: {e}')
                break
            if len(data) != SIZE:
                self.get_logger().warn(
                    f'ignoring packet of unexpected size {len(data)} (expected {SIZE})')
                continue
            latest = data

        if latest is None:
            return

        right_b, left_y = struct.unpack(FMT, latest)
        right_b = bool(right_b)
        left_y = bool(left_y)

        # edge detection: publish only when state changes
        if right_b != self._prev_right_b:
            self.pub_right_b.publish(Bool(data=right_b))
            self.get_logger().info(f'B {"pressed (True)" if right_b else "released (False)"}')
            self._prev_right_b = right_b

        if left_y != self._prev_left_y:
            self.pub_left_y.publish(Bool(data=left_y))
            self.get_logger().info(f'Y {"pressed (True)" if left_y else "released (False)"}')
            self._prev_left_y = left_y

    def destroy_node(self):
        try:
            self.sock.close()
        except Exception:
            pass
        super().destroy_node()


def main(argv=None):
    parser = argparse.ArgumentParser(description='XR B/Y button UDP -> ROS 2 bridge (edge mode)')
    parser.add_argument('--host', type=str, default='0.0.0.0',
                        help='UDP bind host (0.0.0.0 = any interface, 127.0.0.1 = localhost only)')
    parser.add_argument('--port', type=int, default=9870, help='UDP bind port')
    parser.add_argument('--qos-depth', type=int, default=10, help='publisher QoS depth')
    args, ros_argv = parser.parse_known_args(argv if argv is not None else sys.argv[1:])

    rclpy.init(args=ros_argv)
    node = XrButtonBridge(host=args.host, port=args.port, qos_depth=args.qos_depth)
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
