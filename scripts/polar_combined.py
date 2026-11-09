import asyncio
import csv
import math
import os
import sys
import time
from bleak import BleakScanner, BleakClient

POLAR_MAC = "A0:9E:1A:C4:7F:89"
HR_UUID = "00002a37-0000-1000-8000-00805f9b34fb"
PMD_CONTROL = "fb005c81-02e7-f387-1cad-8acd2d8df0c8"
PMD_DATA = "fb005c82-02e7-f387-1cad-8acd2d8df0c8"

ECG, ACC = 0x00, 0x02
NAMES = {ECG: "ECG", ACC: "ACC"}
SETTING_NAMES = {0: "sample_rate", 1: "resolution", 2: "range"}
DURATION_S = int(sys.argv[1]) if len(sys.argv) > 1 else 120

t_start = None
control_event = None
last_response = None
hr_rows, ecg_rows, acc_rows = [], [], []
frames = {ECG: [], ACC: []}
fs = {}
warned = set()


# ---------- PMD control point ----------

def on_control(_sender, data: bytearray):
    global last_response
    last_response = bytes(data)
    control_event.set()


async def send_command(client, payload: bytearray, label: str):
    control_event.clear()
    await client.write_gatt_char(PMD_CONTROL, payload, response=True)
    await asyncio.wait_for(control_event.wait(), timeout=5)
    resp = last_response
    status = resp[3] if len(resp) > 3 else -1
    print(f"{label}: response {resp.hex(' ')} -> {'OK' if status == 0 else f'ERROR {status}'}")
    if status != 0:
        raise RuntimeError(f"{label} failed with status {status}")
    return resp


def parse_settings(resp: bytes):
    settings, i = {}, 5
    while i + 1 < len(resp):
        stype, count = resp[i], resp[i + 1]
        i += 2
        vals = []
        for _ in range(count):
            vals.append(int.from_bytes(resp[i:i + 2], "little"))
            i += 2
        settings[stype] = vals
    return settings


def build_start(mtype: int, cfg: dict):
    cmd = [0x02, mtype]
    for stype, value in cfg.items():
        cmd += [stype, 1, value & 0xFF, value >> 8]
    return bytearray(cmd)


# ---------- data callbacks ----------

def on_hr(_sender, data: bytearray):
    t = round(time.time() - t_start, 3)
    flags = data[0]
    if flags & 0x01:
        hr, idx = int.from_bytes(data[1:3], "little"), 3
    else:
        hr, idx = data[1], 2
    if flags & 0x08:
        idx += 2
    rr = []
    if flags & 0x10:
        while idx + 1 < len(data):
            rr.append(round(int.from_bytes(data[idx:idx + 2], "little") / 1024 * 1000, 1))
            idx += 2
    if rr:
        for value in rr:
            hr_rows.append((t, hr, value))
    else:
        hr_rows.append((t, hr, ""))


def on_pmd(_sender, data: bytearray):
    t = round(time.time() - t_start, 3)
    mtype = data[0]
    ts = int.from_bytes(data[1:9], "little")
    ftype = data[9]
    payload = data[10:]

    if mtype == ECG and ftype == 0x00:
        n = len(payload) // 3
        for k in range(n):
            uv = int.from_bytes(payload[3 * k:3 * k + 3], "little", signed=True)
            ecg_rows.append((t, ts, k, uv))
        frames[ECG].append((ts, n))

    elif mtype == ACC and ftype in (0x00, 0x01, 0x02):
        size = ftype + 1
        step = 3 * size
        n = len(payload) // step
        for k in range(n):
            o = k * step
            x = int.from_bytes(payload[o:o + size], "little", signed=True)
            y = int.from_bytes(payload[o + size:o + 2 * size], "little", signed=True)
            z = int.from_bytes(payload[o + 2 * size:o + 3 * size], "little", signed=True)
            acc_rows.append((t, ts, k, x, y, z))
        frames[ACC].append((ts, n))

    elif (mtype, ftype) not in warned:
        warned.add((mtype, ftype))
        print(f"Unknown frame: type {mtype}, frame type {ftype}, raw {bytes(data[:16]).hex(' ')}...")


# ---------- summary and saving ----------

def frame_report(mtype):
    fr = frames[mtype]
    if len(fr) < 2:
        return f"{NAMES[mtype]}: not enough frames"
    gaps, lost = [], 0
    for (ts_a, _), (ts_b, n_b) in zip(fr, fr[1:]):
        gap = (ts_b - ts_a) / 1e6
        expected = n_b / fs[mtype] * 1000
        gaps.append(gap)
        if gap > 1.5 * expected:
            lost += 1
    total = sum(n for _, n in fr)
    return (f"{NAMES[mtype]}: {len(fr)} frames, {total} samples "
            f"({total / fs[mtype]:.1f} s at {fs[mtype]} Hz), "
            f"frame interval {min(gaps):.1f} to {max(gaps):.1f} ms, gaps: {lost}")


def save(folder):
    os.makedirs(folder, exist_ok=True)
    tables = {
        "hr.csv": (["t_rx_s", "hr_bpm", "rr_ms"], hr_rows),
        "ecg.csv": (["t_rx_s", "sensor_ts_ns", "idx_in_frame", "ecg_uV"], ecg_rows),
        "acc.csv": (["t_rx_s", "sensor_ts_ns", "idx_in_frame", "x_mg", "y_mg", "z_mg"], acc_rows),
    }
    for name, (header, rows) in tables.items():
        with open(os.path.join(folder, name), "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(rows)


def summary():
    print("\n=== Summary ===")
    rr = [r[2] for r in hr_rows if r[2] != ""]
    plausible = [x for x in rr if 300 <= x <= 2000]
    hr_vals = [r[1] for r in hr_rows if r[1] > 0]
    print(f"HR: {len(hr_rows)} rows, {len(rr)} RR intervals, {len(plausible)} within 300-2000 ms")
    if plausible and hr_vals:
        mean_rr = sum(plausible) / len(plausible)
        print(f"    mean RR {mean_rr:.0f} ms (~{60000 / mean_rr:.0f} bpm), "
              f"sensor HR {min(hr_vals)} to {max(hr_vals)} bpm")
    print(frame_report(ECG))
    print(frame_report(ACC))
    if acc_rows:
        mags = [math.sqrt(x * x + y * y + z * z) for *_, x, y, z in acc_rows]
        print(f"ACC: mean magnitude {sum(mags) / len(mags):.0f} mG (at rest expected ~1000 mG = gravity)")


# ---------- main ----------

async def connect_with_retry(attempts=3):
    for attempt in range(1, attempts + 1):
        print(f"Scanning... (attempt {attempt})")
        device = await BleakScanner.find_device_by_address(POLAR_MAC, timeout=15)
        if device is None:
            print("  not found (strap on and wet? phone Bluetooth off?)")
            continue
        try:
            client = BleakClient(device, timeout=20)
            await client.connect()
            print(f"Connected to {device.name}")
            return client
        except Exception as e:
            print(f"  connection failed: {type(e).__name__}")
            await asyncio.sleep(2)
    return None


async def record(client):
    global t_start
    await client.start_notify(PMD_CONTROL, on_control)

    # 1) Ask the sensor which settings it supports
    supported = {}
    for mtype in (ECG, ACC):
        resp = await send_command(client, bytearray([0x01, mtype]), f"Get {NAMES[mtype]} settings")
        supported[mtype] = parse_settings(resp)
        readable = {SETTING_NAMES.get(k, k): v for k, v in supported[mtype].items()}
        print(f"  {NAMES[mtype]} supports: {readable}")

    # 2) Choose settings
    ecg_cfg = {0: 130, 1: 14}
    acc_s = supported[ACC]
    acc_cfg = {
        0: 200 if 200 in acc_s.get(0, []) else max(acc_s.get(0, [200])),
        1: max(acc_s.get(1, [16])),
        2: 8 if 8 in acc_s.get(2, []) else max(acc_s.get(2, [8])),
    }
    fs[ECG], fs[ACC] = ecg_cfg[0], acc_cfg[0]
    print(f"Using ECG {ecg_cfg[0]} Hz / {ecg_cfg[1]} bit, "
          f"ACC {acc_cfg[0]} Hz / {acc_cfg[1]} bit / {acc_cfg[2]} G")

    # 3) Start all streams
    t_start = time.time()
    await client.start_notify(HR_UUID, on_hr)
    await client.start_notify(PMD_DATA, on_pmd)
    await send_command(client, build_start(ECG, ecg_cfg), "Start ECG")
    await send_command(client, build_start(ACC, acc_cfg), "Start ACC")

    print(f"\nRecording {DURATION_S} s. Sit still.\n")
    for sec in range(1, DURATION_S + 1):
        await asyncio.sleep(1)
        if sec % 10 == 0:
            print(f"t={sec:4d}s  HR rows={len(hr_rows)}  ECG={len(ecg_rows)}  ACC={len(acc_rows)}")

    # 4) Stop
    for mtype in (ECG, ACC):
        await send_command(client, bytearray([0x03, mtype]), f"Stop {NAMES[mtype]}")
    await client.stop_notify(PMD_DATA)
    await client.stop_notify(HR_UUID)


async def main():
    global control_event
    control_event = asyncio.Event()

    client = await connect_with_retry()
    if client is None:
        print("Could not connect after 3 attempts")
        return

    try:
        await record(client)
    finally:
        if client.is_connected:
            await client.disconnect()
        print("Disconnected")
        if hr_rows or ecg_rows or acc_rows:
            summary()
            folder = os.path.join("recordings", time.strftime("%Y%m%d_%H%M%S"))
            save(folder)
            print(f"\nSaved hr.csv, ecg.csv, acc.csv to {folder}/")


asyncio.run(main())
