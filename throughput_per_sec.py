import glob, os, re
import pandas as pd
import matplotlib.pyplot as plt

# ==================== Konfigurasi ====================
FILE_PATTERN = "throughput_per_sec_*.csv"  # contoh: throughput_per_sec_1000us.csv
SMOOTH_WINDOW_SEC = 3                      # rolling window (detik) untuk smoothing
FIGSIZE = (14, 6)
TITLE = "Throughput vs Time (Delay Injection)"
X_LABEL = "Time (seconds)"
Y_LABEL = "Throughput (ops/sec)"
# ======================================================

def to_ms_label(text: str) -> str:
    """
    Cari pola '<angka><unit>' di text dan konversi ke 'X ms'.
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

    # format rapi: tanpa .0 jika bilangan bulat, 2–3 desimal jika perlu
    if abs(ms - round(ms)) < 1e-9:
        return f"{int(round(ms))} ms"
    elif ms < 1:
        s = f"{ms:.3f}"
    else:
        s = f"{ms:.2f}"
    s = s.rstrip('0').rstrip('.')
    return f"{s} ms"

def load_throughput_csv(path: str):
    df = pd.read_csv(path)
    # cek kolom waktu
    if "sec" not in df.columns:
        raise ValueError(f"{path}: kolom 'sec' tidak ada.")
    if "ops" not in df.columns:
        raise ValueError(f"{path}: kolom 'ops' tidak ada.")

    # normalisasi waktu agar mulai dari 0
    df["sec"] = df["sec"].astype(int) - df["sec"].min()
    df["ops"] = df["ops"].astype(float)

    # smoothing rolling mean
    df["ops_smooth"] = df["ops"].rolling(
        window=SMOOTH_WINDOW_SEC, center=True, min_periods=1
    ).mean()

    # label dari nama file → konversi ke ms
    raw_label = os.path.splitext(os.path.basename(path))[0].replace("throughput_per_sec_", "")
    label = to_ms_label(raw_label)
    return df, label

# Ambil semua file
files = sorted(glob.glob(FILE_PATTERN))
if not files:
    raise SystemExit(f"Tidak ada file cocok pola: {FILE_PATTERN}")

plt.figure(figsize=FIGSIZE)

for path in files:
    try:
        df, label = load_throughput_csv(path)
        plt.plot(df["sec"], df["ops_smooth"], linewidth=2, alpha=0.95, label=label)
    except Exception as e:
        print(f"Skip {path}: {e}")

# Estetika & keterbacaan
plt.title(TITLE, fontsize=16)
plt.xlabel(X_LABEL)
plt.ylabel(Y_LABEL)
plt.grid(True, linestyle="--", alpha=0.35)
# legend di luar area plot
plt.legend(title="Delay (ms)", frameon=True, loc="center left", bbox_to_anchor=(1.02, 0.5))
plt.tight_layout()
plt.show()
