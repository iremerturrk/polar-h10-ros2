import asyncio
import csv
import time
from bleak import BleakScanner, BleakClient

POLAR_MAC = "A0:9E:1A:C4:7F:89"
PMD_CONTROL = "fb005c81-02e7-f387-1cad-8acd2d8df0c8"
PMD_DATA = "fb005c82-02e7-f387-1cad-8acd2d8df0c8"

# 0x02 = start, 0x00 = ECG, sample rate = 130 Hz (0x0082), resolution = 14 bit (0x000E)
START_ECG = bytearray([0x02, 0x00, 0x00, 0x01, 0x82, 0x00, 0x01, 0x01, 0x0E, 0x00])
STOP_ECG = bytearray([0x03, 0x00])
DURATION_S = 30

samples = []
frames = 0
t_start = None


def on_control(_sender, data: bytearray):
    print(f"Control response: {data.hex(' ')}")
    if len(data) >= 4 and data[0] == 0xF0:
        status = data[3]
        print("  -> OK" if status == 0 else f"  -> ERROR code {status}")


def on_data(_sender, data: bytearray):
    global frames
    if data[0] != 0x00:          # 0x00 = ECG
        return
    sensor_ts = int.from_bytes(data[1:9], "little")
    frame_type = data[9]
    if frame_type != 0x00:
        print(f"Unexpected frame type {frame_type}")
        return
    payload = data[10:]
    n = len(payload) // 3
    t_rx = time.time() - t_start
    for k in range(n):
        uv = int.from_bytes(payload[3 * k:3 * k + 3], "little", signed=True)
        samples.append((round(t_rx, 3), sensor_ts, k, uv))
    frames += 1
    if frames % 10 == 0:
        print(f"t={t_rx:5.1f}s  frames={frames}  samples={len(samples)}  last={samples[-1][3]} uV")


async def main():
    global t_start
    device = await BleakScanner.find_device_by_address(POLAR_MAC, timeout=15)
    if device is None:
        print("Polar H10 not found")
        return
    async with BleakClient(device, timeout=20) as client:
        print("Connected")
        await client.start_notify(PMD_CONTROL, on_control)
        await client.start_notify(PMD_DATA, on_data)
        t_start = time.time()
        await client.write_gatt_char(PMD_CONTROL, START_ECG, response=True)
        await asyncio.sleep(DURATION_S)
        await client.write_gatt_char(PMD_CONTROL, STOP_ECG, response=True)
        await asyncio.sleep(0.5)

    elapsed = DURATION_S
    print(f"\nFrames: {frames}, samples: {len(samples)}, "
          f"effective rate: {len(samples) / elapsed:.1f} Hz (expected ~130)")

    filename = f"ecg_{time.strftime('%Y%m%d_%H%M%S')}.csv"
    with open(filename, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t_rx_s", "sensor_ts_ns", "idx_in_frame", "ecg_uV"])
        w.writerows(samples)
    print(f"Saved to {filename}")


asyncio.run(main())