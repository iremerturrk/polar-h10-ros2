import asyncio
import threading

import rclpy
from rclpy.node import Node
from bleak import BleakScanner, BleakClient

from polar_msgs.msg import HeartRate, RRIntervals, ECG, Accelerometer

HR_UUID = "00002a37-0000-1000-8000-00805f9b34fb"
PMD_CONTROL = "fb005c81-02e7-f387-1cad-8acd2d8df0c8"
PMD_DATA = "fb005c82-02e7-f387-1cad-8acd2d8df0c8"
ECG_TYPE, ACC_TYPE = 0x00, 0x02
ECG_FS = 130


def build_start(mtype, cfg):
    cmd = [0x02, mtype]
    for stype, value in cfg.items():
        cmd += [stype, 1, value & 0xFF, value >> 8]
    return bytearray(cmd)


class PolarH10Node(Node):
    def __init__(self):
        super().__init__('polar_h10_node')
        self.declare_parameter('mac_address', 'A0:9E:1A:C4:7F:89')
        self.declare_parameter('frame_id', 'polar_h10')
        self.declare_parameter('acc_sample_rate', 200)
        self.declare_parameter('acc_range', 8)
        self.mac = self.get_parameter('mac_address').value
        self.frame_id = self.get_parameter('frame_id').value
        self.acc_fs = self.get_parameter('acc_sample_rate').value
        self.acc_range = self.get_parameter('acc_range').value

        self.pub_hr = self.create_publisher(HeartRate, '/polar/heart_rate', 10)
        self.pub_rr = self.create_publisher(RRIntervals, '/polar/rr_intervals', 10)
        self.pub_ecg = self.create_publisher(ECG, '/polar/ecg', 10)
        self.pub_acc = self.create_publisher(Accelerometer, '/polar/acc', 10)

        self.loop = None
        self.stop_event = None
        self.control_event = None
        self.disconnected = None
        self.last_response = None

        self.ble_thread = threading.Thread(target=self.run_ble, daemon=True)
        self.ble_thread.start()

    # ---------- helpers ----------

    def stamp_header(self, msg):
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = self.frame_id

    def safe_publish(self, pub, msg):
        if rclpy.ok():
            try:
                pub.publish(msg)
            except Exception:
                pass

    async def sleep_or_stop(self, seconds):
        try:
            await asyncio.wait_for(self.stop_event.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass

    # ---------- BLE thread ----------

    def run_ble(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.stop_event = asyncio.Event()
        self.control_event = asyncio.Event()
        self.loop.run_until_complete(self.ble_main())
        self.loop.close()

    def stop(self):
        if self.loop is not None and self.stop_event is not None:
            self.loop.call_soon_threadsafe(self.stop_event.set)
        self.ble_thread.join(timeout=10)

    async def ble_main(self):
        while not self.stop_event.is_set():
            client = await self.connect()
            if client is None:
                await self.sleep_or_stop(3)
                continue
            try:
                await self.stream(client)
            except Exception as e:
                self.get_logger().error(f'Streaming error: {type(e).__name__}: {e}')
            finally:
                if client.is_connected:
                    try:
                        for mtype in (ECG_TYPE, ACC_TYPE):
                            await client.write_gatt_char(PMD_CONTROL, bytearray([0x03, mtype]), response=True)
                        await client.disconnect()
                    except Exception:
                        pass
            if not self.stop_event.is_set():
                self.get_logger().warn('Disconnected. Reconnecting in 2 s...')
                await self.sleep_or_stop(2)
        self.get_logger().info('BLE loop stopped')

    async def connect(self):
        self.get_logger().info(f'Scanning for {self.mac}...')
        device = await BleakScanner.find_device_by_address(self.mac, timeout=15)
        if device is None:
            self.get_logger().warn('Polar H10 not found (strap on and wet? phone Bluetooth off?)')
            return None
        self.disconnected = asyncio.Event()
        client = BleakClient(device, timeout=20,
                             disconnected_callback=lambda _c: self.disconnected.set())
        try:
            await client.connect()
        except Exception as e:
            self.get_logger().warn(f'Connection failed: {type(e).__name__}')
            return None
        self.get_logger().info(f'Connected to {device.name}')
        return client

    async def send_command(self, client, payload, label):
        self.control_event.clear()
        await client.write_gatt_char(PMD_CONTROL, payload, response=True)
        await asyncio.wait_for(self.control_event.wait(), timeout=5)
        resp = self.last_response
        status = resp[3] if len(resp) > 3 else -1
        if status != 0:
            raise RuntimeError(f'{label} failed with status {status}')
        self.get_logger().info(f'{label}: OK')

    async def stream(self, client):
        await client.start_notify(PMD_CONTROL, self.on_control)
        await client.start_notify(HR_UUID, self.on_hr)
        await client.start_notify(PMD_DATA, self.on_pmd)
        await self.send_command(client, build_start(ECG_TYPE, {0: ECG_FS, 1: 14}), 'Start ECG')
        await self.send_command(client, build_start(ACC_TYPE, {0: self.acc_fs, 1: 16, 2: self.acc_range}), 'Start ACC')
        self.get_logger().info('Streaming HR, RR, ECG and ACC')

        stop_task = asyncio.ensure_future(self.stop_event.wait())
        disc_task = asyncio.ensure_future(self.disconnected.wait())
        await asyncio.wait({stop_task, disc_task}, return_when=asyncio.FIRST_COMPLETED)
        for task in (stop_task, disc_task):
            task.cancel()

    # ---------- BLE callbacks ----------

    def on_control(self, _sender, data):
        self.last_response = bytes(data)
        self.control_event.set()

    def on_hr(self, _sender, data):
        flags = data[0]
        if flags & 0x01:
            hr, idx = int.from_bytes(data[1:3], 'little'), 3
        else:
            hr, idx = data[1], 2
        if flags & 0x08:
            idx += 2
        rr = []
        if flags & 0x10:
            while idx + 1 < len(data):
                rr.append(int.from_bytes(data[idx:idx + 2], 'little') / 1024 * 1000)
                idx += 2

        msg_hr = HeartRate()
        self.stamp_header(msg_hr)
        msg_hr.bpm = hr
        self.safe_publish(self.pub_hr, msg_hr)

        msg_rr = RRIntervals()
        msg_rr.header = msg_hr.header
        msg_rr.rr_ms = rr
        self.safe_publish(self.pub_rr, msg_rr)

    def on_pmd(self, _sender, data):
        mtype = data[0]
        ts = int.from_bytes(data[1:9], 'little')
        ftype = data[9]
        payload = data[10:]

        if mtype == ECG_TYPE and ftype == 0x00:
            msg = ECG()
            self.stamp_header(msg)
            msg.sensor_timestamp_ns = ts
            msg.sample_rate_hz = float(ECG_FS)
            msg.samples_uv = [int.from_bytes(payload[3 * k:3 * k + 3], 'little', signed=True)
                              for k in range(len(payload) // 3)]
            self.safe_publish(self.pub_ecg, msg)

        elif mtype == ACC_TYPE and ftype in (0x00, 0x01, 0x02):
            size = ftype + 1
            step = 3 * size
            xs, ys, zs = [], [], []
            for k in range(len(payload) // step):
                o = k * step
                xs.append(int.from_bytes(payload[o:o + size], 'little', signed=True))
                ys.append(int.from_bytes(payload[o + size:o + 2 * size], 'little', signed=True))
                zs.append(int.from_bytes(payload[o + 2 * size:o + 3 * size], 'little', signed=True))
            msg = Accelerometer()
            self.stamp_header(msg)
            msg.sensor_timestamp_ns = ts
            msg.sample_rate_hz = float(self.acc_fs)
            msg.x_mg, msg.y_mg, msg.z_mg = xs, ys, zs
            self.safe_publish(self.pub_acc, msg)


def main():
    rclpy.init()
    node = PolarH10Node()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.stop()
        node.destroy_node()
        rclpy.try_shutdown()
