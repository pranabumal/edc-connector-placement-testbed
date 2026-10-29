#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# lib-metrics.sh
# Shared helpers for the Methods §3.6 measurement protocol: RAM/CPU sampling
# (at rest + during transfer) via `docker stats`, and a JSON results writer.
# Source this file from test-case scripts; it defines functions only.
# ─────────────────────────────────────────────────────────────────────────────

# sample_docker_stats_once <container...>
# One-shot, no-stream sample. Prints "name cpu_perc mem_usage_mb" per line.
sample_docker_stats_once() {
  # `|| true`: a transiently-unreachable container (e.g. mid-restart during
  # the architecture matrix runner) must not abort the caller under set -e.
  docker stats --no-stream --format '{{.Name}} {{.CPUPerc}} {{.MemUsage}}' "$@" 2>/dev/null \
    | awk '{
        cpu = $2; gsub(/%/, "", cpu);
        split($3, mem, "/");
        val = mem[1]; unit = "";
        # split leading number from trailing unit, e.g. "123.4MiB"
        match(val, /^[0-9.]+/);
        num = substr(val, RSTART, RLENGTH);
        unit = substr(val, RSTART + RLENGTH);
        mem_mb = num;
        if (unit == "GiB") mem_mb = num * 1024;
        if (unit == "KiB") mem_mb = num / 1024;
        printf "%s %s %.2f\n", $1, cpu, mem_mb;
      }' || true
}

# start_stats_monitor <output_file> <container...>
# Samples every 2s in the background until stop_stats_monitor is called.
# Echoes the background process's PID (capture it: MON_PID=$(start_stats_monitor ...)).
start_stats_monitor() {
  local outfile="$1"; shift
  : > "$outfile"
  # The subshell's own stdout/stderr must NOT inherit the caller's pipe: this
  # function is invoked as `pid=$(start_stats_monitor ...)`, and an
  # unredirected background job holds that pipe open forever (it never
  # exits), so the command substitution would hang waiting for EOF.
  (
    while true; do
      sample_docker_stats_once "$@" >> "$outfile"
      sleep 2
    done
  ) >/dev/null 2>&1 &
  echo $!
}

# stop_stats_monitor <pid>
stop_stats_monitor() {
  local pid="$1"
  kill "$pid" 2>/dev/null || true
  # wait returns 127 if the job was already reaped by the time we get here
  # (a real race, not an error) — under `set -e` an unguarded non-zero exit
  # here would silently abort the whole calling script.
  wait "$pid" 2>/dev/null || true
}

# summarize_stats_file <file> <container_name>
# Prints "min max avg" CPU% and mem_mb for the given container's samples, or
# "0 0 0 0 0 0" if no samples exist.
summarize_stats_file() {
  local file="$1" name="$2"
  awk -v name="$name" '
    $1 == name {
      cpu[n] = $2; mem[n] = $3; n++;
      cpu_sum += $2; mem_sum += $3;
      if (n == 1 || $2 < cpu_min) cpu_min = $2;
      if (n == 1 || $2 > cpu_max) cpu_max = $2;
      if (n == 1 || $3 < mem_min) mem_min = $3;
      if (n == 1 || $3 > mem_max) mem_max = $3;
    }
    END {
      if (n == 0) { print "0 0 0 0 0 0"; exit; }
      printf "%.2f %.2f %.2f %.2f %.2f %.2f\n", cpu_min, cpu_max, cpu_sum/n, mem_min, mem_max, mem_sum/n;
    }
  ' "$file"
}

# json_escape <string> — minimal escaping for embedding in hand-built JSON
json_escape() {
  printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'
}

# ─────────────────────────────────────────────────────────────────────────────
# Distributed measurement helpers (need lib-remote.sh sourced first)
# ─────────────────────────────────────────────────────────────────────────────

# clock_offset_samples <role>
# Offset of the CONTAINER clock on that role's machine against NTP, in seconds
# (one value per NTP reply; positive = the clock is behind NTP). Measured inside
# a container because that is the clock the simulator and receiver stamp with —
# on Docker Desktop it is a VM clock that can differ from the host's own.
# busybox ntpd -w only queries the server; it never sets the clock.
clock_offset_samples() {
  local server="${NTP_SERVER:-time.google.com}"
  ON_ROLE_TIMEOUT=60 on_role "$1" "docker run --rm alpine sh -c 'timeout 8 ntpd -w -d -p $server 2>&1' 2>/dev/null \
    | grep -o 'offset:[-+0-9.e]*' | cut -d: -f2" || true
}

# rtt_ms <from-role> <to-host>
# Average ICMP round-trip time in ms from that role's machine, 10 pings.
rtt_ms() {
  ON_ROLE_TIMEOUT=60 on_role "$1" "ping -c 10 -i 0.2 -q $2 2>/dev/null | tail -1 | awk -F'=' '{print \$2}' | awk -F'/' '{print \$2}'" || true
}

# start_stats_monitor_on <role> <output_file> <container...>
# Samples CPU/RAM every ~2 s on that role's machine (over ssh if remote) until
# stop_stats_monitor_on is called. Echoes a handle "pid:role:tag" for it.
# Sample lines are "name cpu_pct mem_mb" as from sample_docker_stats_once.
#
# The loop runs on the sampled machine, so killing the local wrapper does not
# end it: it carries a unique tag and is killed by that tag on its own machine.
# It also ends by itself after an hour, so an aborted run cannot leave loops
# sampling (and loading) a measured machine indefinitely.
start_stats_monitor_on() {
  local role="$1" outfile="$2"; shift 2
  local tag="mvdmon-$$-$RANDOM"
  : > "$outfile"
  (
    ON_ROLE_TIMEOUT=3700 on_role "$role" "MVD_MON=$tag; end=\$((SECONDS+3600)); while [ \$SECONDS -lt \$end ]; do docker stats --no-stream --format '{{.Name}} {{.CPUPerc}} {{.MemUsage}}' $* 2>/dev/null; sleep 2; done" \
      | awk '{
          cpu = $2; gsub(/%/, "", cpu);
          split($3, mem, "/"); val = mem[1];
          match(val, /^[0-9.]+/); num = substr(val, RSTART, RLENGTH); unit = substr(val, RSTART + RLENGTH);
          mem_mb = num; if (unit == "GiB") mem_mb = num * 1024; if (unit == "KiB") mem_mb = num / 1024;
          printf "%s %s %.2f\n", $1, cpu, mem_mb; fflush();
        }' >> "$outfile"
  ) >/dev/null 2>&1 &
  echo "$!:$role:$tag"
}

# stop_stats_monitor_on <handle>
stop_stats_monitor_on() {
  local pid="${1%%:*}" rest="${1#*:}"
  local role="${rest%%:*}" tag="${rest#*:}"
  # [M]… keeps pkill from matching its own command line
  on_role "$role" "pkill -f '[M]VD_MON=$tag'" >/dev/null 2>&1 || true
  pkill -P "$pid" 2>/dev/null || true
  kill "$pid" 2>/dev/null || true
  wait "$pid" 2>/dev/null || true
}

# sample_stats_on <role> <container...> — one sample, on that role's machine
sample_stats_on() {
  local role="$1"; shift
  on_role "$role" "docker stats --no-stream --format '{{.Name}} {{.CPUPerc}} {{.MemUsage}}' $* 2>/dev/null" \
    | awk '{
        cpu = $2; gsub(/%/, "", cpu);
        split($3, mem, "/"); val = mem[1];
        match(val, /^[0-9.]+/); num = substr(val, RSTART, RLENGTH); unit = substr(val, RSTART + RLENGTH);
        mem_mb = num; if (unit == "GiB") mem_mb = num * 1024; if (unit == "KiB") mem_mb = num / 1024;
        printf "%s %s %.2f\n", $1, cpu, mem_mb;
      }' || true
}
