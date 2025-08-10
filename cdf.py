import glob, os, re
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

# =================== Konfigurasi ===================
FILE_PATTERN = "per_op_latency_*.csv"  # contoh: per_op_latency_1000us.csv
X_UNIT_MS = True                       # True: tampilkan dalam milidetik; False: detik
USE_LOG_X = False                      # True untuk skala log (bagus jika tail lebar)
FIGSIZE = (12, 6)
TITLE = "Latency CDF by Delay Configuration"
X_LABEL = "Latency (ms)" if X_UNIT_MS else "Latency (s)"
Y_LABEL = "CDF (fraction ≤ x)"
# ===================================================

def to_ms_label(text: str) -> str:
    """
    Cari pola '<angka><unit>' pada text dan konversi ke 'X ms'.
    Unit didukung: us/µs, ms, s. Jika tak ditemukan, kembalikan text asli.
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

    # Format rapi
    if abs(ms - round(ms)) < 1e-9:
        return f"{int(round(ms))} ms"
    s = f"{ms:.3f}" if ms < 1 else f"{ms:.2f}"
    s = s.rstrip('0').rstrip('.')
    return f"{s} ms"

def load_latencies_ms(path: str) -> np.ndarray:
    """
    Baca CSV dengan kolom: 'seconds' (float) dan 'op' (opsional).
    Return array latency dalam ms (jika X_UNIT_MS=True) atau s.
    """
    df = pd.read_csv(path)
    if "seconds" not in df.columns:
        raise ValueError(f"{path}: kolom 'seconds' tidak ditemukan.")
    lat_s = df["seconds"].dropna().astype(float).values
    if X_UNIT_MS:
        return lat_s * 1000.0
    return lat_s

def ecdf(values: np.ndarray):
    """
    Hitung Empirical CDF.
    Returns:
      xs: nilai latency terurut
      ys: proporsi kumulatif (0..1)
    """
    if values.size == 0:
        return np.array([]), np.array([])
    xs = np.sort(values)
    n = xs.size
    ys = np.arange(1, n + 1, dtype=float) / n
    return xs, ys

# Kumpulkan file
files = sorted(glob.glob(FILE_PATTERN))
if not files:
    raise SystemExit(f"Tidak ada file yang cocok: {FILE_PATTERN}")

plt.figure(figsize=FIGSIZE)

# Plot setiap file sebagai satu garis CDF
for path in files:
    try:
        lat = load_latencies_ms(path)
        xs, ys = ecdf(lat)
        if xs.size == 0:
            print(f"Skip {os.path.basename(path)}: tidak ada data.")
            continue

        raw_label = os.path.splitext(os.path.basename(path))[0].replace("per_op_latency_", "")
        label = to_ms_label(raw_label)
        plt.plot(xs, ys, linewidth=2, alpha=0.95, label=label)
    except Exception as e:
        print(f"Skip {path}: {e}")

# Estetika & keterbacaan
plt.title(TITLE, fontsize=15)
plt.xlabel(X_LABEL)
plt.ylabel(Y_LABEL)
plt.grid(True, linestyle="--", alpha=0.35)

# Legend di luar area plot supaya tidak menutupi kurva
plt.legend(title="Delay (ms)", frameon=True, loc="center left", bbox_to_anchor=(1.02, 0.5))

# Opsi log-scale untuk X
if USE_LOG_X:
    plt.xscale("log")  # nilai 0 akan di-clip otomatis oleh matplotlib

plt.tight_layout()
plt.show()
