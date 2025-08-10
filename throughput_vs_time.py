import os, glob
import pandas as pd
import matplotlib.pyplot as plt
from math import floor

# ======================= Konfigurasi =======================
# Pola file yang mau diplot (aktifkan sesuai kebutuhan)
CSV_PER_SEC_PATTERN = "latency_per_sec_*us.csv"  # contoh: latency_per_sec_100us.csv (kolom: sec/t_sec/time & ops/throughput)
CSV_RAW_PATTERN     = "latency_data_*.csv"       # contoh: latency_data_fs-delay-100ms.csv (kolom: timestamp_ms, latency_ms, phase)
LOG_PATTERN         = "latency_x*ms.log"         # contoh: latency_x100ms.log  (baris: "timestamp_ms,...")

FAULT_START_SEC = 40           # set manual (detik). Gunakan None untuk coba deteksi otomatis dari kolom 'phase'
SMOOTH_WINDOW_SEC = 3          # rolling average agar kurva tidak bergerigi
FIGSIZE = (14, 6)
TITLE = "Delay Injection: Throughput vs Time"
# ===========================================================

def _mk_per_sec_full(per_sec_df):
    """Lengkapi detik hilang dan terapkan smoothing."""
    full_idx = pd.RangeIndex(per_sec_df["t_sec"].min(), per_sec_df["t_sec"].max() + 1)
    per_sec_df = per_sec_df.set_index("t_sec").reindex(full_idx, fill_value=0).rename_axis("t_sec").reset_index()
    per_sec_df["ops_smooth"] = per_sec_df["ops"].rolling(
        window=SMOOTH_WINDOW_SEC, center=True, min_periods=1
    ).mean()
    return per_sec_df

def load_csv_per_sec(path: str):
    """
    CSV per-detik—mencoba tebak nama kolom umum:
      waktu: ['t_sec', 'sec', 'time', 'second']
      nilai: ['ops', 'throughput', 'qps']
    """
    df = pd.read_csv(path)
    # deteksi kolom waktu
    for c in ["t_sec", "sec", "time", "second"]:
        if c in df.columns:
            tcol = c
            break
    else:
        raise ValueError(f"{path}: tidak menemukan kolom waktu (t_sec/sec/time/second).")
    # deteksi kolom nilai
    for c in ["ops", "throughput", "qps"]:
        if c in df.columns:
            vcol = c
            break
    else:
        # fallback: jika hanya ada 2 kolom, pakai kolom kedua
        if len(df.columns) == 2:
            cols = list(df.columns)
            tcol, vcol = cols[0], cols[1]
        else:
            raise ValueError(f"{path}: tidak menemukan kolom nilai (ops/throughput/qps).")

    per_sec = df[[tcol, vcol]].rename(columns={tcol: "t_sec", vcol: "ops"}).copy()
    per_sec["t_sec"] = per_sec["t_sec"].astype(int)
    per_sec["ops"] = per_sec["ops"].astype(float)
    per_sec = _mk_per_sec_full(per_sec)

    label = os.path.splitext(os.path.basename(path))[0].replace("latency_per_sec_", "")
    return per_sec, None, label

def load_csv_raw(path: str):
    """
    CSV mentah—kolom: timestamp_ms, latency_ms, phase (ops dihitung per detik).
    """
    df = pd.read_csv(path)
    if "timestamp_ms" not in df.columns:
        raise ValueError(f"{path}: kolom 'timestamp_ms' tidak ada.")
    t0 = df["timestamp_ms"].min()
    df["t_sec"] = (df["timestamp_ms"] - t0) // 1000
    per_sec = df.groupby("t_sec").size().rename("ops").reset_index()
    per_sec = _mk_per_sec_full(per_sec)

    fault_start = None
    if "phase" in df.columns:
        nz = df[df["phase"] != "baseline"]
        if not nz.empty:
            fault_start = floor(((nz["timestamp_ms"].min() - t0) / 1000.0))

    label = os.path.splitext(os.path.basename(path))[0].replace("latency_data_", "")
    return per_sec, fault_start, label

def load_log_raw(path: str):
    """
    Log mentah—baris "timestamp_ms,..."
    """
    timestamps = []
    with open(path, "r") as f:
        for line in f:
            if "," not in line:
                continue
            ts = line.split(",")[0].strip()
            if ts.isdigit():
                timestamps.append(int(ts))

    if not timestamps:
        raise ValueError(f"{path}: tidak ada timestamp valid.")
    s = pd.Series(timestamps)
    t0 = s.min()
    t_sec = (s - t0) // 1000
    per_sec = t_sec.value_counts().sort_index().rename("ops").reset_index().rename(columns={"index":"t_sec"})
    per_sec = _mk_per_sec_full(per_sec)

    label = os.path.splitext(os.path.basename(path))[0].replace("latency_", "")
    return per_sec, None, label

# --- Kumpulkan file ---
files = []
files += sorted(glob.glob(CSV_PER_SEC_PATTERN))
files += sorted(glob.glob(CSV_RAW_PATTERN))
files += sorted(glob.glob(LOG_PATTERN))

if not files:
    raise SystemExit("Tidak ada file yang cocok. Cek pola CSV/LOG di bagian konfigurasi.")

plt.figure(figsize=FIGSIZE)

fault_candidates = []
for p in files:
    try:
        if os.path.basename(p).startswith("latency_per_sec_"):
            per_sec, fs, label = load_csv_per_sec(p)
        elif p.endswith(".csv"):
            per_sec, fs, label = load_csv_raw(p)
        else:
            per_sec, fs, label = load_log_raw(p)

        if fs is not None:
            fault_candidates.append(fs)

        plt.plot(
            per_sec["t_sec"] - per_sec["t_sec"].min(),   # normalisasi mulai dari 0
            per_sec["ops_smooth"],
            linewidth=2,
            alpha=0.95,
            label=label
        )
    except Exception as e:
        print(f"Skip {p}: {e}")

# --- Garis vertikal Fault Start ---
if FAULT_START_SEC is not None:
    fs = FAULT_START_SEC
elif fault_candidates:
    fault_candidates.sort()
    fs = fault_candidates[len(fault_candidates)//2]  # median
else:
    fs = None

if fs is not None:
    plt.axvline(fs, linestyle="--", linewidth=1.8, label="Fault Start")

# --- Estetika & keterbacaan ---
plt.title(TITLE, fontsize=16)
plt.xlabel("Time (seconds)")
plt.ylabel("Throughput (ops/sec)")
plt.grid(True, linestyle="--", alpha=0.35)
# Legend di luar plot biar tidak menutupi garis
plt.legend(title="Delay Config", frameon=True, ncol=1, loc="center left", bbox_to_anchor=(1.02, 0.5))
plt.tight_layout()
plt.show()
