import csv
import os
import time

import rclpy
from rclpy.node import Node

from polar_msgs.msg import HeartRate, RRIntervals, ECG, Accelerometer


def stamp_ns(msg):
    return msg.header.stamp.sec * 1_000_000_000 + msg.header.stamp.nanosec


class ReliabilityLogger(Node):
    def __init__(self):
        super().__init__('polar_reliability_logger')
        self.declare_parameter('output_dir', os.path.expanduser('~/polar_tests/reliability'))
        out_dir = self.get_parameter('output_dir').value
        os.makedirs(out_dir, exist_ok=True)
        self.path = os.path.join(out_dir, time.strftime('log_%Y%m%d_%H%M%S.csv'))
        self.file = open(self.path, 'w', newline='')
        self.writer = csv.writer(self.file)
        self.writer.writerow(['topic', 'recv_ns', 'stamp_ns', 'sensor_ts_ns', 'n_samples', 'value'])
        self.counts = {'hr': 0, 'rr': 0, 'ecg': 0, 'acc': 0}

        self.create_subscription(HeartRate, '/polar/heart_rate', self.on_hr, 100)
        self.create_subscription(RRIntervals, '/polar/rr_intervals', self.on_rr, 100)
        self.create_subscription(ECG, '/polar/ecg', self.on_ecg, 100)
        self.create_subscription(Accelerometer, '/polar/acc', self.on_acc, 100)
        self.create_timer(10.0, self.report)
        self.get_logger().info(f'Logging to {self.path}')

    def now_ns(self):
        return self.get_clock().now().nanoseconds

    def write(self, topic, msg, sensor_ts, n, value):
        self.writer.writerow([topic, self.now_ns(), stamp_ns(msg), sensor_ts, n, value])
        self.counts[topic] += 1

    def on_hr(self, msg):
        self.write('hr', msg, '', 1, msg.bpm)

    def on_rr(self, msg):
        self.write('rr', msg, '', len(msg.rr_ms), ';'.join(f'{x:.1f}' for x in msg.rr_ms))

    def on_ecg(self, msg):
        self.write('ecg', msg, msg.sensor_timestamp_ns, len(msg.samples_uv), '')

    def on_acc(self, msg):
        self.write('acc', msg, msg.sensor_timestamp_ns, len(msg.x_mg), '')

    def report(self):
        self.file.flush()
        c = self.counts
        self.get_logger().info(f"messages: hr={c['hr']} rr={c['rr']} ecg={c['ecg']} acc={c['acc']}")

    def close(self):
        self.file.flush()
        self.file.close()


def main():
    rclpy.init()
    node = ReliabilityLogger()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.close()
        node.destroy_node()
        rclpy.try_shutdown()
