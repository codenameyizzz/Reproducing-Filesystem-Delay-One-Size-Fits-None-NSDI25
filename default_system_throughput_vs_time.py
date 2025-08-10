import os, glob
import pandas as pd
import matplotlib.pyplot as plt
from math import floor

# configuration
# use one of the patterns below (or both):
CSV_PATTERN = "latency_data_*.csv"     # e.g., latency_data_fs-delay-100ms.csv
LOG_PATTERN = "latency_x*ms.log"       # e.g., latency_x100ms.log

SMOOTH_WINDOW_SEC = 3                  # rolling avg (seconds)
FAULT_START_OVERRIDE = None            # set a second value to force the vertical line position, or None
FIGSIZE = (14, 6)
TITLE = "Filesystem Delay Injection: Throughput vs Time"

def load_from_csv(path: str):
    """CSV with columns: timestamp_ms, latency_ms, phase (baseline/fault)."""
    df = pd.read_csv(path)
    if "timestamp_ms" not in df.columns:
        raise ValueError(f"{path}: 'timestamp_ms' column not found.")
    t0 = df["timestamp_ms"].min()
    df["t_sec"] = (df["timestamp_ms"] - t0) // 1000

    # Per-second 
    per_sec = df.groupby("t_sec").size().rename("ops").reset_index()

    # Fill missing seconds
    full_idx = pd.RangeIndex(per_sec["t_sec"].min(), per_sec["t_sec"].max() + 1)
    per_sec = per_sec.set_index("t_sec").reindex(full_idx, fill_value=0).rename_axis("t_sec").reset_index()

    # Smoothing
    per_sec["ops_smooth"] = per_sec["ops"].rolling(window=SMOOTH_WINDOW_SEC,
                                                   center=True, min_periods=1).mean()

    # Estimate fault start if there is any row with phase != baseline
    fault_start = None
    if "phase" in df.columns:
        fault_rows = df[df["phase"] != "baseline"]
        if not fault_rows.empty:
            fault_start = floor(((fault_rows["timestamp_ms"].min() - t0) / 1000.0))

    label = os.path.splitext(os.path.basename(path))[0].replace("latency_data_", "")
    return per_sec, fault_start, label

def load_from_log(path: str):
    """Log with lines like 'timestamp_ms,...' (as in your reference)."""
    timestamps = []
    with open(path, "r") as f:
        for line in f:
            if "," not in line:
                continue
            ts = line.strip().split(",")[0]
            if ts.isdigit():
                timestamps.append(int(ts))

    if not timestamps:
        raise ValueError(f"{path}: no valid timestamps found.")

    s = pd.Series(timestamps)
    t0 = s.min()
    t_sec = (s - t0) // 1000
    per_sec = t_sec.value_counts().sort_index().rename("ops").reset_index()
    per_sec = per_sec.rename(columns={"index": "t_sec"})

    full_idx = pd.RangeIndex(per_sec["t_sec"].min(), per_sec["t_sec"].max() + 1)
    per_sec = per_sec.set_index("t_sec").reindex(full_idx, fill_value=0).rename_axis("t_sec").reset_index()

    per_sec["ops_smooth"] = per_sec["ops"].rolling(window=SMOOTH_WINDOW_SEC,
                                                   center=True, min_periods=1).mean()

    label = os.path.splitext(os.path.basename(path))[0].replace("latency_", "")
    return per_sec, None, label  # fault_start is unknown from a plain log

# Collect files
files = sorted(glob.glob(CSV_PATTERN)) + sorted(glob.glob(LOG_PATTERN))
if not files:
    raise SystemExit("No files match the pattern. Check CSV_PATTERN/LOG_PATTERN.")

plt.figure(figsize=FIGSIZE)

fault_candidates = []
for path in files:
    try:
        if path.endswith(".csv"):
            per_sec, fs, label = load_from_csv(path)
            if fs is not None:
                fault_candidates.append(fs)
        else:
            per_sec, fs, label = load_from_log(path)
        plt.plot(per_sec["t_sec"], per_sec["ops_smooth"], linewidth=1.8, label=label)
    except Exception as e:
        print(f"Skip {path}: {e}")

# Vertical line for Fault Start
if FAULT_START_OVERRIDE is not None:
    fs = FAULT_START_OVERRIDE
elif fault_candidates:
    # use median for stability if files differ slightly
    fault_candidates.sort()
    fs = fault_candidates[len(fault_candidates)//2]
else:
    fs = None

if fs is not None:
    plt.axvline(fs, linestyle="--", linewidth=1.5, label="Fault Start")

# Styling
plt.title(TITLE)
plt.xlabel("Time (seconds)")
plt.ylabel("Throughput (ops/sec)")
plt.grid(True, linestyle="--", alpha=0.5)
plt.legend(title="Delay Config")
plt.tight_layout()
plt.show()
