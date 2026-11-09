import asyncio
from bleak import BleakScanner, BleakClient

POLAR_MAC = "A0:9E:1A:C4:7F:89"
HR_MEASUREMENT_UUID = "00002a37-0000-1000-8000-00805f9b34fb"


def parse_hr(data: bytearray):
    flags = data[0] #control bits that tells us how to evaluate the data
    #bitwise AND
    hr_is_uint16 = flags & 0x01
    rr_present = flags & 0x10
    energy_present = flags & 0x08

    if hr_is_uint16:
        hr = int.from_bytes(data[1:3], "little")
        idx = 3
    else:
        hr = data[1]
        idx = 2

    if energy_present:
        idx += 2

    rr_ms = []
    if rr_present:
        while idx + 1 < len(data):
            rr_raw = int.from_bytes(data[idx:idx + 2], "little")
            rr_ms.append(rr_raw / 1024 * 1000)
            idx += 2

    return hr, rr_ms


def on_hr(_sender, data: bytearray):
    hr, rr = parse_hr(data)
    print(f"raw={data.hex(' ')}  HR={hr} bpm  RR={[round(x) for x in rr]} ms")


async def main():
    print("Scanning...")
    device = await BleakScanner.find_device_by_address(POLAR_MAC, timeout=15)
    if device is None:
        print("Polar H10 not found (strap on? phone disconnected?)")
        return

    print(f"Found: {device.name}")
    async with BleakClient(device) as client:
        print(f"Connected: {client.is_connected}")
        await client.start_notify(HR_MEASUREMENT_UUID, on_hr)
        await asyncio.sleep(30)
        await client.stop_notify(HR_MEASUREMENT_UUID)
    print("Disconnected")


asyncio.run(main())