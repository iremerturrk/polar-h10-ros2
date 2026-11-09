import csv
import sys
import matplotlib.pyplot as plt

filename = sys.argv[1]
uv, frame_ts = [], []
with open(filename) as f:
    for row in csv.DictReader(f):
        uv.append(int(row["ecg_uV"]))
        if row["idx_in_frame"] == "0":
            frame_ts.append(int(row["sensor_ts_ns"]))

fs = 130
t = [i / fs for i in range(len(uv))]

gaps_ms = [(b - a) / 1e6 for a, b in zip(frame_ts, frame_ts[1:])]
print(f"Frames: {len(frame_ts)}")
print(f"Frame interval: min {min(gaps_ms):.1f} ms, max {max(gaps_ms):.1f} ms "
      f"(expected {73 / fs * 1000:.1f} ms)")
print(f"Data duration: {len(uv) / fs:.1f} s")

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 6))
ax1.plot(t, uv, linewidth=0.6)
ax1.set_title("Polar H10 ECG, full recording")
ax1.set_xlabel("Time (s)")
ax1.set_ylabel("µV")

mask = [5 <= x <= 10 for x in t]
ax2.plot([x for x, m in zip(t, mask) if m], [y for y, m in zip(uv, mask) if m], linewidth=0.8)
ax2.set_title("Zoom: 5 s to 10 s")
ax2.set_xlabel("Time (s)")
ax2.set_ylabel("µV")

plt.tight_layout()
plt.savefig(filename.replace(".csv", ".png"), dpi=150)
plt.show()