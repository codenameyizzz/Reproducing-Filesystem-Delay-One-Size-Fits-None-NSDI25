#!/usr/bin/env bash
set -euo pipefail

if [ $# -ne 2 ]; then
  echo "Usage: $0 <delay_ms> <operations_count>"
  echo "Example: $0 100 500  (Injects 100ms delay, runs 500 operations)"
  exit 1
fi

DELAY_MS="$1"
TOTAL_OPS="$2"
LABEL="fs-delay-${DELAY_MS}ms"

# --- Configuration ---
CHARYBDEFS_DIR="$HOME/charybdefs"
MOUNT_POINT="/mnt/slowfs"
REAL_DATA_DIR="/tmp/io_test_data_real"
DOCKER_COMPOSE_FILE="docker-compose-simple.yml"
FAULT_INJECTOR_SCRIPT="charyb_fault.py"
OUTDIR="io_bench_results/$(date +%Y%m%d_%H%M%S)_${LABEL}"
mkdir -p "$OUTDIR"
RAW_LOG="$OUTDIR/latency_data.csv"

# --- Cleanup function ---
cleanup() {
  echo -e "\n[CLEANUP] Cleaning up all processes and mounts..."
  docker compose -f "$DOCKER_COMPOSE_FILE" down --volumes --remove-orphans > /dev/null 2>&1 || true
  sudo pkill -f charybdefs || true
  sleep 2
  sudo umount -l "$MOUNT_POINT" > /dev/null 2>&1 || true
  sudo rm -rf "${REAL_DATA_DIR:?}"/*
  sudo rm -rf "${MOUNT_POINT:?}"/*
  echo "[CLEANUP] Done."
}

# --- Execution ---
trap cleanup EXIT

echo "[SETUP] Starting initial cleanup..."
cleanup

echo "[SETUP] Creating required directories..."
sudo mkdir -p "$MOUNT_POINT" "$REAL_DATA_DIR"
sudo chown "$USER:$USER" "$MOUNT_POINT" "$REAL_DATA_DIR"

echo "[SETUP] Starting CharybdeFS in the background..."
sudo "$CHARYBDEFS_DIR/charybdefs" "$MOUNT_POINT" -o allow_other,modules=subdir,subdir="$REAL_DATA_DIR"
if ! mount | grep -q "$MOUNT_POINT"; then
  echo "[ERROR] Failed to mount CharybdeFS at $MOUNT_POINT"
  exit 1
fi
echo "[SETUP] CharybdeFS mounted successfully."

echo "[SETUP] Starting benchmark container..."
docker compose -f "$DOCKER_COMPOSE_FILE" up -d
docker exec benchmark-runner apt-get -qq update && docker exec benchmark-runner apt-get -qq install -y coreutils > /dev/null
echo "[SETUP] Container ready."

# --- Benchmark ---
echo "[INFO] Label       : $LABEL"
echo "[INFO] Delay       : ${DELAY_MS}ms"
echo "[INFO] Total Ops   : $TOTAL_OPS"
echo "[INFO] Output File : $RAW_LOG"

# Write CSV header
echo "timestamp_ms,latency_ms,phase" > "$RAW_LOG"

# --- PHASE 1: BASELINE (NO FAULT) ---
echo -e "\n--- PHASE 1: Running Baseline Benchmark (No Fault) ---"
python3 "$FAULT_INJECTOR_SCRIPT" --clear > /dev/null
for (( i=1; i<=TOTAL_OPS; i++ )); do
  START_MS=$(date +%s%3N)
  docker exec benchmark-runner dd if=/dev/zero of=/data/test.dat bs=4k count=1 conv=fsync >/dev/null 2>&1
  END_MS=$(date +%s%3N)
  LATENCY=$((END_MS - START_MS))
  echo "$START_MS,$LATENCY,baseline" >> "$RAW_LOG"
done

# --- PHASE 2: WITH FAULT ---
echo -e "\n--- PHASE 2: Injecting ${DELAY_MS}ms sync-delay Fault and Continuing Benchmark ---"
DELAY_US=$((DELAY_MS * 1000))
python3 "$FAULT_INJECTOR_SCRIPT" --sync-delay "$DELAY_US" > /dev/null
for (( i=1; i<=TOTAL_OPS; i++ )); do
  START_MS=$(date +%s%3N)
  docker exec benchmark-runner dd if=/dev/zero of=/data/test.dat bs=4k count=1 conv=fsync >/dev/null 2>&1
  END_MS=$(date +%s%3N)
  LATENCY=$((END_MS - START_MS))
  echo "$START_MS,$LATENCY,fault" >> "$RAW_LOG"
done

# --- Final analysis ---
analyze_phase() {
    local phase=$1
    local data_file=$2

    # Extract latency values for the given phase
    LATENCIES=$(grep ",${phase}$" "$data_file" | cut -d',' -f2)

    if [ -z "$LATENCIES" ]; then
        echo "No data for phase '$phase'."
        return
    fi

    SORTED_LAT=$(echo "$LATENCIES" | sort -n)
    COUNT=$(echo "$SORTED_LAT" | wc -l)
    TOTAL_TIME=$(echo "$LATENCIES" | awk '{s+=$1} END {print s}')
    THROUGHPUT=$(awk -v count="$COUNT" -v time="$TOTAL_TIME" 'BEGIN {if (time > 0) printf "%.2f", count / (time / 1000); else print "N/A"}')

    P50=$(echo "$SORTED_LAT" | awk -v c=$COUNT 'NR==int(c*0.50+0.5)')
    P99=$(echo "$SORTED_LAT" | awk -v c=$COUNT 'NR==int(c*0.99+0.5)')

    echo "  - Throughput : $THROUGHPUT ops/sec"
    echo "  - Latency p50: $P50 ms"
    echo "  - Latency p99: $P99 ms"
}

echo -e "\n\n================================================="
echo "           EXPERIMENT RESULT SUMMARY"
echo "================================================="
echo -e "\n### BASELINE RESULTS (NO FAULT) ###"
analyze_phase "baseline" "$RAW_LOG"
echo -e "\n### RESULTS WITH ${DELAY_MS}MS SYNC DELAY ###"
analyze_phase "fault" "$RAW_LOG"
echo -e "\n================================================="
echo -e "\n[SUCCESS] Experiment complete. Raw data saved to: $RAW_LOG"
