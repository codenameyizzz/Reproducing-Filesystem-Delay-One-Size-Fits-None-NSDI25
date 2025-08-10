import os, glob, re
import pandas as pd
import matplotlib.pyplot as plt

# ======================= Konfigurasi =======================
FILE_PATTERN = "latency_per_sec_*.csv"  # sebelumnya: ..._*us.csv
PREFERRED_METRICS = ["p50_ms", "median_ms", "latency_ms", "avg_ms", "mean_ms"]
SMOOTH_WINDOW_SEC = 5
FAULT_START_SEC = None
FIGSIZE = (14, 6)
TITLE = "Delay Injection: Latency vs Time"
Y_LABEL = "Latency (ms)"
# ===========================================================

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

    # format rapi: tanpa .0 jika bulat; jika tidak, trim desimal
    if abs(ms - round(ms)) < 1e-9:
        return f"{int(round(ms))} ms"
    s = f"{ms:.3f}" if ms < 1 else f"{ms:.2f}"
    s = s.rstrip('0').rstrip('.')
    return f"{s} ms"

def pick_time_and_metric_columns(df: pd.DataFrame):
    # deteksi kolom waktu
    tcol = None
    for c in ["t_sec", "sec", "time", "second"]:
        if c in df.columns:
            tcol = c
            break
    if tcol is None:
        raise ValueError("Tidak menemukan kolom waktu (t_sec/sec/time/second).")

    # deteksi kolom metrik
    mcol = None
    for c in PREFERRED_METRICS:
        if c in df.columns:
            mcol = c
            break

    # fallback: jika hanya ada 2 kolom, pakai kolom kedua sebagai metrik
    if mcol is None and len(df.columns) == 2:
        other = [c for c in df.columns if c != tcol][0]
        mcol = other

    if mcol is None:
        raise ValueError(f"Tidak menemukan kolom metrik dari kandidat: {PREFERRED_METRICS}")

    return tcol, mcol

def build_series_from_csv(path: str):
    df = pd.read_csv(path)
    tcol, mcol = pick_time_and_metric_columns(df)

    # salin dan rapikan
    s = df[[tcol, mcol]].rename(columns={tcol: "t_sec", mcol: "lat"}).copy()
    s["t_sec"] = s["t_sec"].astype(int)
    s["lat"] = s["lat"].astype(float)

    # lengkapi detik yang kosong
    full_idx = pd.RangeIndex(s["t_sec"].min(), s["t_sec"].max() + 1)
    s = s.set_index("t_sec").reindex(full_idx).rename_axis("t_sec").reset_index()

    # interpolasi ringan agar garis halus di titik kosong
    s["lat"] = s["lat"].interpolate(limit_direction="both")

    # smoothing (rolling median biar tahan outlier; ganti ke .mean() kalau mau)
    s["lat_smooth"] = s["lat"].rolling(
        window=SMOOTH_WINDOW_SEC, center=True, min_periods=1
    ).median()

    # label dari nama file → konversi ke ms
    raw_label = os.path.splitext(os.path.basename(path))[0].replace("latency_per_sec_", "")
    label = to_ms_label(raw_label)
    return s, label

# ==== Kumpulkan & plot ====
files = sorted(glob.glob(FILE_PATTERN))
if not files:
    raise SystemExit(f"Tidak ada file yang cocok: {FILE_PATTERN}")

plt.figure(figsize=FIGSIZE)

for path in files:
    try:
        per_sec, label = build_series_from_csv(path)
        # normalisasi waktu mulai dari 0 agar antar file comparable
        x = per_sec["t_sec"] - per_sec["t_sec"].min()
        y = per_sec["lat_smooth"]
        plt.plot(x, y, linewidth=2, alpha=0.95, label=label)
    except Exception as e:
        print(f"Skip {path}: {e}")

# Garis vertikal Fault Start (opsional)
if FAULT_START_SEC is not None:
    plt.axvline(FAULT_START_SEC, linestyle="--", linewidth=1.8, label="Fault Start")

# Estetika & keterbacaan
plt.title(TITLE, fontsize=16)
plt.xlabel("Time (seconds)")
plt.ylabel(Y_LABEL)
plt.grid(True, linestyle="--", alpha=0.35)
# legend di luar area plot supaya tidak menutupi garis
plt.legend(title="Delay (ms)", frameon=True, loc="center left", bbox_to_anchor=(1.02, 0.5))
plt.tight_layout()
plt.show()
