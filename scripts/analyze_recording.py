import os
import sys
import numpy as np
import pandas as pd
import neurokit2 as nk
import matplotlib.pyplot as plt

folder = sys.argv[1]
FS = 130
SKIP_S = 2.0                 # startup transient
HR_RANGE = (40, 180)         # bpm, typical adult range
RR_RANGE = (300, 2000)       # ms

ecg = pd.read_csv(os.path.join(folder, "ecg.csv"))
hr = pd.read_csv(os.path.join(folder, "hr.csv"))

# ---------- ECG time axis on the host clock ----------
# Polar timestamp belongs to the last sample of each frame.
n_in_frame = ecg.groupby("sensor_ts_ns")["idx_in_frame"].transform("count")
ecg["t_sensor_s"] = ecg["sensor_ts_ns"] / 1e9 - (n_in_frame - 1 - ecg["idx_in_frame"]) / FS
frames = ecg.groupby("sensor_ts_ns").agg(t_rx=("t_rx_s", "first"))
offset = np.median(frames["t_rx"].values - frames.index.values / 1e9)
ecg["t"] = ecg["t_sensor_s"] + offset

ecg = ecg[ecg["t"] >= ecg["t"].min() + SKIP_S].reset_index(drop=True)
t = ecg["t"].values
raw = ecg["ecg_uV"].values

# ---------- R peak detection with NeuroKit2 ----------
signals, info = nk.ecg_process(raw, sampling_rate=FS)
clean = signals["ECG_Clean"].values
peaks = np.asarray(info["ECG_R_Peaks"])
peak_t = t[peaks]
rr_ecg = np.diff(peak_t) * 1000
rr_ecg_t = peak_t[1:]
hr_ecg = 60000 / rr_ecg

# ---------- Polar data ----------
polar_hr = hr[hr["hr_bpm"] > 0].groupby("t_rx_s")["hr_bpm"].first()
polar_rr = hr.dropna(subset=["rr_ms"])

# ---------- Comparison on a common 1 Hz grid ----------
start = max(rr_ecg_t[0], polar_hr.index[0])
end = min(rr_ecg_t[-1], polar_hr.index[-1])
grid = np.arange(np.ceil(start), np.floor(end))
hr_ecg_grid = np.interp(grid, rr_ecg_t, hr_ecg)
hr_polar_grid = np.interp(grid, polar_hr.index.values, polar_hr.values)
diff = hr_ecg_grid - hr_polar_grid

n_beats_ecg = int(np.sum((peak_t >= start) & (peak_t <= end)))
n_beats_polar = int(np.sum((polar_rr["t_rx_s"] >= start) & (polar_rr["t_rx_s"] <= end)))


def pct_in(values, lo, hi):
    values = np.asarray(values, dtype=float)
    return 100 * np.mean((values >= lo) & (values <= hi))


print(f"Analysis window: {start:.1f} to {end:.1f} s ({end - start:.0f} s)\n")
print("=== Typical range check ===")
print(f"ECG-derived HR within {HR_RANGE} bpm: {pct_in(hr_ecg, *HR_RANGE):.1f} %")
print(f"ECG-derived RR within {RR_RANGE} ms: {pct_in(rr_ecg, *RR_RANGE):.1f} %")
print(f"Polar HR within {HR_RANGE} bpm:       {pct_in(polar_hr.values, *HR_RANGE):.1f} %")
print(f"Polar RR within {RR_RANGE} ms:       {pct_in(polar_rr['rr_ms'], *RR_RANGE):.1f} %\n")
print("=== HR comparison (ECG-derived vs Polar) ===")
print(f"Mean HR: ECG {hr_ecg_grid.mean():.1f} bpm, Polar {hr_polar_grid.mean():.1f} bpm")
print(f"Mean absolute difference: {np.abs(diff).mean():.1f} bpm, max {np.abs(diff).max():.1f} bpm")
print(f"Correlation: r = {np.corrcoef(hr_ecg_grid, hr_polar_grid)[0, 1]:.2f}")
print(f"Beats in window: ECG {n_beats_ecg}, Polar RR {n_beats_polar}")
print(f"Mean RR: ECG {rr_ecg.mean():.0f} ms, Polar {polar_rr['rr_ms'].mean():.0f} ms")

# ---------- Figure 1: peak detection ----------
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 6))
ax1.plot(t, clean, linewidth=0.6)
ax1.plot(peak_t, clean[peaks], "rx", markersize=5)
ax1.set_title("ECG (NeuroKit2 cleaned) with detected R peaks")
ax1.set_xlabel("Time (s)")
ax1.set_ylabel("µV")
z0 = t[0] + 10
mask = (t >= z0) & (t <= z0 + 10)
pmask = (peak_t >= z0) & (peak_t <= z0 + 10)
ax2.plot(t[mask], clean[mask], linewidth=0.8)
ax2.plot(peak_t[pmask], clean[peaks][pmask], "rx", markersize=8)
ax2.set_title("Zoom: 10 s")
ax2.set_xlabel("Time (s)")
ax2.set_ylabel("µV")
plt.tight_layout()
plt.savefig(os.path.join(folder, "peaks.png"), dpi=150)

# ---------- Figure 2: HR comparison ----------
fig, ax = plt.subplots(figsize=(12, 4))
ax.plot(rr_ecg_t, hr_ecg, ".", alpha=0.5, label="ECG-derived (beat to beat)")
ax.plot(grid, hr_ecg_grid, linewidth=1.5, label="ECG-derived (1 Hz)")
ax.step(polar_hr.index, polar_hr.values, where="post", linewidth=1.5, label="Polar HR service")
ax.set_xlabel("Time (s)")
ax.set_ylabel("Heart rate (bpm)")
ax.set_title("HR calculated from ECG vs HR reported by Polar")
ax.legend()
plt.tight_layout()
plt.savefig(os.path.join(folder, "hr_comparison.png"), dpi=150)
plt.show()

# ---------- Beat-to-beat RR comparison (aligned sequences) ----------
pr = polar_rr[(polar_rr["t_rx_s"] >= start - 2) & (polar_rr["t_rx_s"] <= end + 2)]["rr_ms"].values
er = rr_ecg[(rr_ecg_t >= start - 2) & (rr_ecg_t <= end + 2)]
best = None
for lag in range(-10, 11):
    a, b = (er[lag:], pr) if lag >= 0 else (er, pr[-lag:])
    n = min(len(a), len(b))
    if n < 20:
        continue
    mae = np.mean(np.abs(a[:n] - b[:n]))
    if best is None or mae < best[1]:
        best = (lag, mae, a[:n], b[:n])
lag, mae, a, b = best
print("\n=== Beat-to-beat RR comparison (ECG vs Polar RR) ===")
print(f"Matched beats: {len(a)} (best alignment lag {lag})")
print(f"Mean absolute difference: {mae:.1f} ms, median {np.median(np.abs(a - b)):.1f} ms")
print(f"Within 20 ms: {100 * np.mean(np.abs(a - b) <= 20):.1f} %")
print(f"Correlation: r = {np.corrcoef(a, b)[0, 1]:.2f}")

# ---------- Smoothed HR comparison ----------
hr_ecg_smooth = pd.Series(hr_ecg_grid).rolling(5, center=True, min_periods=1).mean().values
d2 = hr_ecg_smooth - hr_polar_grid
print("\n=== HR comparison with ECG HR smoothed over 5 s ===")
print(f"Mean absolute difference: {np.abs(d2).mean():.1f} bpm, max {np.abs(d2).max():.1f} bpm")
print(f"Correlation: r = {np.corrcoef(hr_ecg_smooth, hr_polar_grid)[0, 1]:.2f}")

# ---------- Figure 3: RR beat to beat ----------
fig, ax = plt.subplots(figsize=(12, 4))
ax.plot(a, "o-", markersize=3, linewidth=1, label="RR from ECG (NeuroKit2)")
ax.plot(b, "s-", markersize=3, linewidth=1, alpha=0.7, label="RR from Polar HR service")
ax.set_xlabel("Beat number")
ax.set_ylabel("RR interval (ms)")
ax.set_title("Beat-to-beat RR intervals: ECG vs Polar")
ax.legend()
plt.tight_layout()
plt.savefig(os.path.join(folder, "rr_comparison.png"), dpi=150)
plt.show()
