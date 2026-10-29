#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# diag-monitor.sh <seconds> <output prefix>
# Diagnostic, not part of the measurement protocol. Run on the machine of the
# provider's Data Plane: once per second, the TCP state of the Data Plane's
# connections (public API :8284 to the consumer, :5050 to the data source),
# read inside the container's network namespace with ss -tinm, and the
# machine's CPU (vmstat, including steal time). Writes <prefix>-ss.txt and
# <prefix>-vmstat.txt.
# ─────────────────────────────────────────────────────────────────────────────
set -uo pipefail
dur="${1:?seconds}"; out="${2:?output prefix}"
SUDO=""; [[ "$(id -u)" == 0 ]] || SUDO="sudo -n"
pid="$($SUDO docker inspect -f '{{.State.Pid}}' provider-dp)"
vmstat -t 1 "$dur" > "$out-vmstat.txt" &
end=$((SECONDS + dur))
while (( SECONDS < end )); do
  echo "@ $(date +%s.%N)"
  $SUDO nsenter -t "$pid" -n ss -tinm state established '( sport = :8284 or dport = :5050 )'
  sleep 1
done > "$out-ss.txt"
wait
