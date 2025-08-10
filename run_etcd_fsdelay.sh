#!/usr/bin/env bash
# run_etcd_fsdelay.sh
# Baseline vs WAL delay on the LEADER node's FUSE-mounted data dir.

set -euo pipefail

# ===== CONFIG DEFAULTS =====
OPS="${OPS:-200}"                         # number of put ops
MODE="${1:-baseline}"                     # baseline | delay
LEADER_TARGET="${LEADER_TARGET:-etcd2}"   # we want etcd2 as leader (the slow WAL)
WAL_DELAY_US="${WAL_DELAY_US:-0}"         # e.g. 0, 100000, 300000, 750000
RESULTS_DIR="${RESULTS_DIR:-results}"
OUT_PREFIX="${OUT_PREFIX:-etcd_fsdelay}"
ETCDCTL="${ETCDCTL:-/usr/local/bin/etcdctl}"
ETCD_CONTAINER="${ETCD_CONTAINER:-etcd0}" # container to exec etcdctl from
ENDPOINTS="${ENDPOINTS:-http://etcd0:2379,http://etcd1:2379,http://etcd2:2379}"
PYTHON="${PYTHON:-python3}"
CHARYB="${CHARYB:-./charyb_fault.py}"

# charybdefs control (your daemon listens here)
CHARYB_HOST="${CHARYB_HOST:-127.0.0.1}"
CHARYB_PORT="${CHARYB_PORT:-9090}"

# Methods and regex to hit etcd WAL on the slow node (matches your working setup)
WAL_METHODS="${WAL_METHODS:-open,create,write,write_buf,fsync,fdatasync,fsyncdir,flush}"
WAL_REGEX="${WAL_REGEX:-(^|.*/)member/wal/.*}"   # path as charybdefs sees it (starts with /)

# Optional: verify the delay is actually seen on the WAL path (host-side)
VERIFY_DELAY="${VERIFY_DELAY:-1}"

mkdir -p "$RESULTS_DIR"

echo "Target leader   : ${LEADER_TARGET:-'(current)'}"
echo "Mode            : $MODE"
echo "Ops             : $OPS"
[[ "$MODE" == "delay" ]] && echo "WAL delay (us)  : $WAL_DELAY_US"
echo "Endpoints       : $ENDPOINTS"
echo

# Ensure Thrift stub path for charybdefs client
export PYTHONPATH="${PYTHONPATH:-$HOME/charybdefs/gen-py}"

# --- helpers -------------------------------------------------------------

print_health() {
  docker exec "$ETCD_CONTAINER" "$ETCDCTL" --endpoints="$ENDPOINTS" endpoint status -w table || true
}

name_to_endpoint() {
  case "$1" in
    etcd0) echo "http://etcd0:2379";;
    etcd1) echo "http://etcd1:2379";;
    etcd2) echo "http://etcd2:2379";;
    *)     echo ""; return 1;;
  esac
}

# Parse leader from *table* output (robust; no JSON)
get_leader_name_from_table() {
  docker exec "$ETCD_CONTAINER" "$ETCDCTL" --endpoints="$ENDPOINTS" endpoint status -w table \
  | awk -F'|' '
    /http:\/\// {
      ep=$2; islead=$10
      gsub(/^[ \t]+|[ \t]+$/, "", ep)
      gsub(/^[ \t]+|[ \t]+$/, "", islead)
      if (islead=="true") {
        if (ep ~ /etcd0:2379/) { print "etcd0"; exit }
        if (ep ~ /etcd1:2379/) { print "etcd1"; exit }
        if (ep ~ /etcd2:2379/) { print "etcd2"; exit }
      }
    }'
}

# Get ID by name from *table*
id_by_name_table() {
  local name="$1"
  docker exec "$ETCD_CONTAINER" "$ETCDCTL" --endpoints="$ENDPOINTS" member list -w table \
  | awk -F'|' -v N="$name" '
      /[0-9a-fA-F]+/ && $0 ~ (" "N" ") {
        id=$2; gsub(/^[ \t]+|[ \t]+$/, "", id); print id; exit
      }'
}

ensure_leader_target() {
  local want="$1"
  [[ -z "$want" ]] && { echo "[info] No LEADER_TARGET set"; return 0; }
  echo "[info] Forcing leader to: $want"

  for attempt in {1..6}; do
    cur="$(get_leader_name_from_table || true)"
    echo "[info] current leader: ${cur:-unknown}"

    if [[ -n "${cur:-}" && "$cur" == "$want" ]]; then
      echo "Leader OK: $cur"; return 0
    fi

    # try move-leader if we know both sides
    if [[ -n "${cur:-}" ]]; then
      tgt_id="$(id_by_name_table "$want" || true)"
      cur_ep="$(name_to_endpoint "$cur" || true)"
      if [[ -n "${cur_ep:-}" && -n "${tgt_id:-}" ]]; then
        if docker exec "$ETCD_CONTAINER" "$ETCDCTL" --endpoints="$cur_ep" move-leader "$tgt_id" >/dev/null 2>&1; then
          sleep 1
          continue
        fi
      fi
    fi

    echo "[warn] move-leader failed; forcing new election"
    if [[ -n "${cur:-}" ]]; then
      docker stop "$cur" >/dev/null 2>&1 || true
      sleep 3
      docker start "$cur" >/dev/null 2>&1 || true
    else
      docker restart "$want" >/dev/null 2>&1 || true
    fi
    sleep 2
  done
  echo "WARN: could not force leader to $want (continuing)"
}

inject_or_clear() {
  if [[ "$MODE" == "baseline" ]]; then
    echo "Charybdefs: clear faults"
    "$PYTHON" "$CHARYB" clear --host "$CHARYB_HOST" --port "$CHARYB_PORT"
  else
    echo "Charybdefs: delay on WAL"
    "$PYTHON" "$CHARYB" delay \
      --host "$CHARYB_HOST" --port "$CHARYB_PORT" \
      --methods "$WAL_METHODS" \
      --delay-us "$WAL_DELAY_US" \
      --prob-permil 1000 \
      --regex "$WAL_REGEX"
  fi
}

verify_delay() {
  [[ "$VERIFY_DELAY" != "1" || "$MODE" != "delay" ]] && return 0
  # host-side quick check on etcd2's WAL path (your slow FUSE mount)
  "$PYTHON" - <<PY
import os,time
p="/mnt/slowfs/etcd2/member/wal/_probe"
t=time.time()
with open(p,"wb") as f:
  f.write(b"x"*4096); os.fsync(f.fileno())
os.remove(p)
print(f"[verify] host WAL fsync elapsed ~{time.time()-t:.3f}s (inj≈{${WAL_DELAY_US}/1e6:.3f}s)")
PY
}

run_workload() {
  leader_name="$(get_leader_name_from_table || echo etcd2)"
  leader_ep="$(name_to_endpoint "$leader_name")"

  ts="$(date +%Y%m%d_%H%M%S)"
  label="${OUT_PREFIX}_${MODE}_${leader_name}_$(printf '%dus' "$WAL_DELAY_US")"
  run_dir="${RESULTS_DIR}/${ts}_${label}"
  mkdir -p "$run_dir"

  raw_csv="${run_dir}/per_op_latency.csv"
  thr_csv="${run_dir}/throughput_per_sec.csv"
  lat_csv="${run_dir}/latency_per_sec.csv"

  : > "$raw_csv"; echo "op,seconds" >> "$raw_csv"

  echo ">>> Workload: ${OPS} x PUT to ${leader_name} (${leader_ep})"
  start_ns=$(date +%s%N)
  ok=0; fail=0
  for i in $(seq 1 "$OPS"); do
    tf="$run_dir/t.$$"
    if /usr/bin/time -f '%e' -o "$tf" \
        docker exec "$ETCD_CONTAINER" "$ETCDCTL" --endpoints="$leader_ep" put "k$i" "v$i" >/dev/null 2>&1; then
      ok=$((ok+1)); printf '%d,%s\n' "$i" "$(cat "$tf")" >> "$raw_csv"
    else
      fail=$((fail+1)); printf '%d,NaN\n' "$i" >> "$raw_csv"
    fi
    rm -f "$tf"
  done
  end_ns=$(date +%s%N)
  wall_s=$(awk -v s="$start_ns" -v e="$end_ns" 'BEGIN{printf "%.3f", (e-s)/1e9}')

  thr=$(awk -v ops="$ok" -v t="$wall_s" 'BEGIN{ if (t>0) printf "%.2f", ops/t; else print "0.00"}')
  p50=$(awk -F, 'NR>1&&$2!="NaN"{print $2}' "$raw_csv" | sort -n | awk '{a[NR]=$1} END{if(NR){i=int(0.50*NR+0.5); if(i<1)i=1; print a[i]} else print "NaN"}')
  p95=$(awk -F, 'NR>1&&$2!="NaN"{print $2}' "$raw_csv" | sort -n | awk '{a[NR]=$1} END{if(NR){i=int(0.95*NR+0.5); if(i<1)i=1; print a[i]} else print "NaN"}')
  p99=$(awk -F, 'NR>1&&$2!="NaN"{print $2}' "$raw_csv" | sort -n | awk '{a[NR]=$1} END{if(NR){i=int(0.99*NR+0.5); if(i<1)i=1; print a[i]} else print "NaN"}')

  echo
  echo "Summary:"
  echo "  ok=$ok fail=$fail  wall=${wall_s}s  throughput=${thr} ops/s"
  echo "  p50=${p50}s  p95=${p95}s  p99=${p99}s"
  echo "Saved per-op latency CSV : $raw_csv"

  # Aggregate per second into two more CSVs
  "$PYTHON" - "$raw_csv" "$thr_csv" "$lat_csv" <<'PY'
import sys, csv, math
from statistics import mean

raw, thr_out, lat_out = sys.argv[1:4]
rows = []
with open(raw, newline='') as f:
    rd = csv.DictReader(f)
    for r in rd:
        try:
            s = float(r['seconds'])
            if not (s == s):  # skip NaN
                continue
        except Exception:
            continue
        rows.append(s)

bins = {}  # sec bucket -> latencies
elapsed = 0.0
for s in rows:
    elapsed += s
    sec = int(math.floor(elapsed))
    bins.setdefault(sec, []).append(s)

with open(thr_out, 'w', newline='') as f:
    w=csv.writer(f); w.writerow(['sec','ops'])
    for sec in sorted(bins):
        w.writerow([sec, len(bins[sec])])

with open(lat_out, 'w', newline='') as f:
    w=csv.writer(f); w.writerow(['sec','avg_latency_s'])
    for sec in sorted(bins):
        b = bins[sec]
        w.writerow([sec, mean(b) if b else 'NaN'])
PY

  echo "Saved throughput/s CSV   : $thr_csv"
  echo "Saved latency/s CSV      : $lat_csv"
  echo ">>> END workload"
}

# ===== MAIN ==============================================================
echo "== Cluster =="
print_health; echo
ensure_leader_target "$LEADER_TARGET"
print_health; echo
inject_or_clear
verify_delay
run_workload
[[ "$MODE" == "delay" ]] && "$PYTHON" "$CHARYB" clear --host "$CHARYB_HOST" --port "$CHARYB_PORT" || true
