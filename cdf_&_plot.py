import pandas as pd
import matplotlib.pyplot as plt
import glob, os, re
import numpy as np


FILE_PATTERN = "per_op_latency_*.csv"   # match this into your file name
FIGSIZE = (12, 6)


def to_ms_label(text: str) -> str:
    """
    Ambil pola '<angka><unit>' dari text dan konversi ke 'X ms'.
    Unit didukung: us/µs, ms, s. Jika tidak ketemu, kembalikan text asli.
    """
    m = re.search(r'(?i)(\d+(?:\.\d+)?)\s*(µs|us|ms|s)\b', text)
    if not m:
        return text
    val = float(m.group(1))
    unit = m.group(2).lower()

    if unit in ('µs', 'us'):
        ms = val / 1000.0
    elif unit == 'ms':
        ms = val
    elif unit == 's':
        ms = val * 1000.0
    else:
        return text

    if abs(ms - round(ms)) < 1e-9:
        return f"{int(round(ms))} ms"
    s = f"{ms:.3f}" if ms < 1 else f"{ms:.2f}"
    s = s.rstrip('0').rstrip('.')
    return f"{s} ms"

# take all the csv file by pattern
files = sorted(glob.glob(FILE_PATTERN))
if not files:
    raise SystemExit(f"Tidak ada file cocok pola: {FILE_PATTERN}")

colors = plt.cm.tab10.colors

# line plot
plt.figure(figsize=FIGSIZE)
for i, path in enumerate(files):
    df = pd.read_csv(path)
    if not {"op", "seconds"}.issubset(df.columns):
        print(f"Skip {os.path.basename(path)}: kolom 'op' atau 'seconds' tidak ada.")
        continue
    raw_label = os.path.splitext(os.path.basename(path))[0].replace("per_op_latency_", "")
    label = to_ms_label(raw_label)

    plt.plot(
        df["op"],
        df["seconds"] * 1000.0,  # konversi ke ms
        label=label,
        color=colors[i % len(colors)],
        linewidth=1.5,
        alpha=0.9
    )

plt.title("Latency per Operation (Line Plot)", fontsize=14)
plt.xlabel("Operation #")
plt.ylabel("Latency (ms)")
plt.grid(True, linestyle="--", alpha=0.5)
plt.legend(title="Delay (ms)")
plt.tight_layout()
plt.show()

# cdf plot
plt.figure(figsize=FIGSIZE)
for i, path in enumerate(files):
    df = pd.read_csv(path)
    if "seconds" not in df.columns:
        print(f"Skip {os.path.basename(path)}: kolom 'seconds' tidak ada.")
        continue

    lat_ms = df["seconds"].astype(float) * 1000.0
    lat_ms = lat_ms.dropna().values
    if lat_ms.size == 0:
        print(f"Skip {os.path.basename(path)}: tidak ada data latency.")
        continue

    sorted_lat = np.sort(lat_ms)
    cdf = np.arange(1, len(sorted_lat) + 1, dtype=float) / len(sorted_lat)

    raw_label = os.path.splitext(os.path.basename(path))[0].replace("per_op_latency_", "")
    label = to_ms_label(raw_label)

    plt.plot(
        sorted_lat,
        cdf,
        label=label,
        color=colors[i % len(colors)],
        linewidth=1.5,
        alpha=0.9
    )

plt.title("Latency CDF", fontsize=14)
plt.xlabel("Latency (ms)")
plt.ylabel("Cumulative Probability")
plt.grid(True, linestyle="--", alpha=0.5)
plt.legend(title="Delay (ms)", loc="lower right")
plt.tight_layout()
plt.show()
