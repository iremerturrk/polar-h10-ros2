import glob
import os
import sys
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

FS = {'ecg': 130.0, 'acc': 200.0}

if len(sys.argv) > 1:
    path = sys.argv[1]
else:
    path = max(glob.glob(os.path.expanduser('~/polar_tests/reliability/log_*.csv')), key=os.path.getmtime)
df = pd.read_csv(path, dtype={'sensor_ts_ns': 'Int64'})
print(f'Log: {path}\n')

t0 = df['recv_ns'].min()
df['t'] = (df['recv_ns'] - t0) / 1e9
df['ros_latency_ms'] = (df['recv_ns'] - df['stamp_ns']) / 1e6

# ---------- rates ----------
print('=== Rates ===')
for topic in ['hr', 'rr', 'ecg', 'acc']:
    d = df[df.topic == topic]
    if len(d) < 2:
        print(f'{topic}: no data')
        continue
    dur = (d.recv_ns.iloc[-1] - d.recv_ns.iloc[0]) / 1e9
    ia = np.diff(d.recv_ns.values) / 1e6
    line = f'{topic:4s}: {len(d)} msgs in {dur:.1f} s, {(len(d) - 1) / dur:.3f} msg/s'
    if topic in FS:
        line += f', {d.n_samples.iloc[1:].sum() / dur:.1f} samples/s (expected {FS[topic]:.0f})'
    line += f', arrival interval {ia.min():.0f} to {ia.max():.0f} ms'
    print(line)

# ---------- missing data ----------
print('\n=== Missing data ===')
for topic in ['ecg', 'acc']:
    d = df[df.topic == topic]
    ts = d.sensor_ts_ns.astype('int64').values
    n = d.n_samples.values
    gaps = np.diff(ts)
    expected = n[1:] / FS[topic] * 1e9
    big = gaps > 1.5 * expected
    lost = int(np.sum(np.round(gaps[big] / expected[big]) - 1))
    print(f'{topic}: {len(d)} frames, sensor frame interval {gaps.min() / 1e6:.1f} to {gaps.max() / 1e6:.1f} ms, '
          f'gaps: {int(big.sum())}, estimated lost frames: {lost}, duplicates: {int(np.sum(gaps == 0))}')

hr = df[df.topic == 'hr']
hr_gaps = np.diff(hr.recv_ns.values) / 1e9
print(f'hr: gaps longer than 1.5 s: {int(np.sum(hr_gaps > 1.5))}')

rr = df[df.topic == 'rr']
empty = int((rr.n_samples == 0).sum())
rr_sum_s = sum(float(x) for v in rr.value.dropna().astype(str) for x in v.split(';') if x) / 1000
rr_dur = (rr.recv_ns.iloc[-1] - rr.recv_ns.iloc[0]) / 1e9
print(f'rr: {empty} packets without RR, sum of RR {rr_sum_s:.1f} s vs elapsed {rr_dur:.1f} s '
      f'({100 * rr_sum_s / rr_dur:.1f} %)')

# ---------- ROS transport latency ----------
print('\n=== ROS transport latency (logger receive minus publish stamp) ===')
for topic in ['hr', 'rr', 'ecg', 'acc']:
    lat = df[df.topic == topic].ros_latency_ms
    print(f'{topic:4s}: median {lat.median():.2f} ms, 95th percentile {lat.quantile(0.95):.2f} ms, max {lat.max():.2f} ms')

# ---------- BLE delay variation ----------
print('\n=== BLE delay variation (publish stamp minus sensor timestamp, relative) ===')
ble = {}
for topic in ['ecg', 'acc']:
    d = df[df.topic == topic]
    diff_ns = d.stamp_ns.values - d.sensor_ts_ns.astype('int64').values
    rel_ms = (diff_ns - diff_ns.min()) / 1e6
    tt = d.t.values
    slope, intercept = np.polyfit(tt, rel_ms, 1)
    resid = rel_ms - (slope * tt + intercept)
    resid -= resid.min()
    ble[topic] = (tt, resid)
    print(f'{topic}: clock drift {slope * 1000:.1f} ppm, delay variation median {np.median(resid):.1f} ms, '
          f'95th percentile {np.percentile(resid, 95):.1f} ms, max {resid.max():.1f} ms')

# ---------- figure ----------
fig, axes = plt.subplots(3, 1, figsize=(12, 9))
for topic, marker in [('ecg', '.'), ('acc', '.')]:
    d = df[df.topic == topic]
    axes[0].plot(d.t.values[1:], np.diff(d.recv_ns.values) / 1e6, marker, markersize=2, label=topic.upper())
axes[0].set_title('Arrival interval of messages')
axes[0].set_ylabel('ms')
axes[0].legend()
for topic in ['ecg', 'acc']:
    tt, resid = ble[topic]
    axes[1].plot(tt, resid, '.', markersize=2, label=topic.upper())
axes[1].set_title('BLE delay variation (relative, drift removed)')
axes[1].set_ylabel('ms')
axes[1].legend()
axes[2].hist([df[df.topic == t].ros_latency_ms for t in ['hr', 'rr', 'ecg', 'acc']],
             bins=50, label=['HR', 'RR', 'ECG', 'ACC'])
axes[2].set_title('ROS transport latency')
axes[2].set_xlabel('ms')
axes[2].legend()
for ax in axes[:2]:
    ax.set_xlabel('Time (s)')
plt.tight_layout()
out = path.replace('.csv', '_reliability.png')
plt.savefig(out, dpi=150)
print(f'\nSaved {out}')
plt.show()
