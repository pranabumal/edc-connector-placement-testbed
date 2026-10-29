#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# run-all-tests.sh
# One measurement run (thesis §3.6): TC-1..TC-4 against the architecture that
# is deployed right now, with every machine measured where it runs.
#
# Writes results/<timestamp>-<arch>-<timing>/ with the raw inputs and summary.json:
#   meta.json            architecture, timing profile, machines per role,
#                        limits, git commit
#   network.tsv          round-trip times between the machines
#   clock.tsv            each machine's container clock vs NTP, before and
#                        after every test case
#   run.log              negotiation times, and each transfer's run id + id
#   tcN.out              the test script's own output
#   receiver-tcN.json    arrivals logged by the receiver
#   created-tcN.tsv      each transfer's creation time on consumer-cp
#   at-rest.txt, stats-tcN-<machine>.txt   CPU/RAM samples
#   summary.json         computed by summarize-run.py
#
# Env vars:
#   ARCH_LABEL   tag for this run; default: the deployed architecture
#   RESULTS_DIR  default <repo>/results
#   TCS          test cases to run; default "tc1 tc2 tc3 tc4". "s<bytes>"
#                runs the payload sweep at that size (6-payload-sweep.sh);
#                "pull-tc1" … "pull-tc4", "pull-s<bytes>" run the same asset as
#                a PULL transfer (7-pull-transfer.sh)
#   TC1_REPEAT … TC4_REPEAT   transfers per test case (thesis protocol: 5)
#   APP_ON       where the test-case scripts run — the consumer's application
#                that asks for the catalogue, negotiates and requests transfers:
#                "consumer" (default when distributed): on the consumer's
#                machine, next to its Control Plane and the receiver, like a
#                data platform on the consumer's site; every timed step is
#                then on that machine's clock and none crosses the controller's
#                network. "controller": on the machine running this script.
#   LINK_CUT_AT, LINK_CUT_FOR   pull-timed-linkcut only (set D, Hybrid): cut the
#                link between the provider's Control Plane and Data Plane machines
#                LINK_CUT_AT s (default 20) after the test case starts, for
#                LINK_CUT_FOR s (default 70); scripts/link-cut.sh
#   RUN_TAG      appended to the run directory name and recorded in meta.json
#                (e.g. "A-r2", "B-par"); MEASUREMENT_SET the protocol's set
#                (A–D, thesis Chapter 3)
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=./lib-endpoints.sh
source "$SCRIPT_DIR/lib-endpoints.sh"
# shellcheck source=./lib-remote.sh
source "$SCRIPT_DIR/lib-remote.sh"
# shellcheck source=./lib-metrics.sh
source "$SCRIPT_DIR/lib-metrics.sh"

ARCH_LABEL="${ARCH_LABEL:-$ARCH}"
TIMING="${TIMING:-default}"          # from deploy/.endpoints.env (deploy.sh --timing)
RESULTS_DIR="${RESULTS_DIR:-$REPO_ROOT/results}"
TCS="${TCS:-tc1 tc2 tc3 tc4}"
RUN_DIR="$RESULTS_DIR/$(date +%Y%m%dT%H%M%S)-$ARCH_LABEL-$TIMING${RUN_TAG:+-$RUN_TAG}"
mkdir -p "$RUN_DIR"
export RUN_LOG="$RUN_DIR/run.log"
: > "$RUN_LOG"

APP_ON="${APP_ON:-consumer}"
[[ "$DISTRIBUTED" == 1 && -n "$(ssh_of_role consumer)" ]] || APP_ON=controller

# run_tc_script <script> [args] — one test-case script, as the consumer's
# application: on the consumer's machine (APP_ON=consumer) or here. Its RUN_LOG
# lines (negotiation times, transfer ids) end up in this run's RUN_LOG.
APP_ENV_VARS="TC1_REPEAT TC2_REPEAT TC3_REPEAT TC4_REPEAT PULL_REPEAT PULL_VIA PULL_RATE PULL_DURATION PULL_PARALLEL PULL_DEADLINE_MS PULL_NEW_CONN PUSH_INTERVAL_S POLICY_VALID_S TIMED_AFTER_S TIMED_INTERVAL_S ENF_DURATION TERMINATE_AFTER_S NEG_MAX_ATTEMPTS TRANSFER_MAX_ATTEMPTS TRANSFER_WAIT_S TC4_SOURCE"
run_tc_script() {
  local script="$1"; shift
  if [[ "$APP_ON" != consumer ]]; then
    bash "$script" "$@"
    return
  fi
  # The script writes next to its RUN_LOG (7-pull-transfer.sh: the pull
  # client's output); everything in that directory comes back into RUN_DIR.
  local remote_dir="/tmp/mvd-run-$$-$RANDOM" v rc=0
  local env="MVD_LOCAL_ROLES=consumer RUN_LOG=$remote_dir/run.log"
  for v in $APP_ENV_VARS; do [[ -n "${!v:-}" ]] && env="$env $v='${!v}'"; done
  ON_ROLE_TIMEOUT=3600 on_role consumer "mkdir -p $remote_dir && : > $remote_dir/run.log; $env bash scripts/$(basename "$script") $*" || rc=$?
  on_role consumer "cat $remote_dir/run.log; rm -f $remote_dir/run.log" >> "$RUN_LOG" || true
  on_role consumer "tar -C $remote_dir -cf - . ; rm -rf $remote_dir" | tar -C "$RUN_DIR" -xf - 2>/dev/null || true
  return $rc
}

# (a function, not an associative array: macOS ships bash 3.2)
tc_script() {
  case "$1" in
    tc1) echo "$SCRIPT_DIR/2-tc1-realtime-control.sh" ;;
    tc2) echo "$SCRIPT_DIR/3-tc2-high-freq-sensors.sh" ;;
    tc3) echo "$SCRIPT_DIR/4-tc3-video-stream.sh" ;;
    tc4) echo "$SCRIPT_DIR/5-tc4-triggered-alert.sh" ;;
    *)   echo "run-all-tests.sh: unknown test case '$1'" >&2; exit 1 ;;
  esac
}
# The connector containers whose CPU/RAM is reported (§3.6), each sampled on
# the machine it runs on under this architecture.
MEASURED="provider-cp provider-cp-db provider-dp provider-dp-db consumer-cp consumer-dp"

# containers_on <machine-role> — the measured containers running on that machine
containers_on() {
  local h c out=""
  h="$(host_of_role "$1")"
  for c in $MEASURED; do
    [[ "$(host_of_role "$(role_of_container "$c")")" == "$h" ]] && out="$out $c"
  done
  echo "$out"
}

# Stops every running CPU/RAM monitor, on the machine it samples. Also runs if
# the script exits early, so no sampling loop is left behind on any machine.
MON_PIDS=()
stop_monitors() {
  local h
  # ${arr[@]+...}: bash 3.2 treats an empty array as unset under set -u
  for h in ${MON_PIDS[@]+"${MON_PIDS[@]}"}; do stop_stats_monitor_on "$h"; done
  MON_PIDS=()
}
trap stop_monitors EXIT

record_clocks() {   # record_clocks <label>
  local m v
  for m in $(machines); do
    for v in $(clock_offset_samples "$m"); do
      printf '%s\t%s\t%s\t%s\n' "$1" "$m" "$(host_of_role "$m")" "$v" >> "$RUN_DIR/clock.tsv"
    done
  done
}

echo ""
echo "################################################################"
echo "#  Measurement run — architecture: $ARCH_LABEL, timing: $TIMING"
echo "#  Consumer application (test-case scripts) runs on: $APP_ON"
echo "#  $(date)"
echo "#  Output: $RUN_DIR"
echo "################################################################"

# ── Context: where everything runs, and the network between the machines ─────
python3 - "$RUN_DIR/meta.json" <<EOF
import json, subprocess, sys
roles = {r: {"host": h, "roles_on_machine": m} for r, h, m in [
$(for r in $ROLES; do printf '    ("%s", "%s", "%s"),\n' "$r" "$(host_of_role "$r")" "$(roles_on_machine "$r")"; done)
]}
try:
    commit = subprocess.check_output(["git", "-C", "$REPO_ROOT", "rev-parse", "--short", "HEAD"], text=True).strip()
    dirty = bool(subprocess.check_output(["git", "-C", "$REPO_ROOT", "status", "--porcelain", "--", "docker", "deploy", "scripts", "mvd"], text=True).strip())
except Exception:
    commit, dirty = None, None
json.dump({
    "architecture": "$ARCH_LABEL",
    "application_on": "$APP_ON",
    "timing": "$TIMING",
    "edc_transfer_wait_ms": int("${EDC_TRANSFER_WAIT_MS:-}" or 1000),
    "edc_negotiation_wait_ms": int("${EDC_NEGOTIATION_WAIT_MS:-}" or 1000),
    "started_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
    "distributed": bool($DISTRIBUTED),
    "provider_cp_role": "$PROVIDER_CP_ROLE",
    "provider_dp_role": "$PROVIDER_DP_ROLE",
    "roles": roles,
    "limits": {"edge": ["${EDGE_CPU:-}", "${EDGE_MEM:-}"], "cloud": ["${CLOUD_CPU:-}", "${CLOUD_MEM:-}"],
               "consumer": ["${CONSUMER_CPU:-}", "${CONSUMER_MEM:-}"]},
    "tc4_source": "$TC4_SOURCE",
    "repeats": {"tc1": "${TC1_REPEAT:-5}", "tc2": "${TC2_REPEAT:-5}", "tc3": "${TC3_REPEAT:-5}", "tc4": "${TC4_REPEAT:-5}"},
    "measurement_set": "${MEASUREMENT_SET:-}", "run_tag": "${RUN_TAG:-}",
    "pull": {"via": "${PULL_VIA:-direct}", "rate": "${PULL_RATE:-}", "duration_s": "${PULL_DURATION:-}",
             "parallel": "${PULL_PARALLEL:-}", "deadline_ms": "${PULL_DEADLINE_MS:-}", "new_connection": "${PULL_NEW_CONN:-0}", "repeat": "${PULL_REPEAT:-}"},
    "git_commit": commit, "git_dirty": dirty,
}, open(sys.argv[1], "w"), indent=2)
EOF

# Background load on each machine (other services share the consumer's host)
for m in $(machines); do
  printf '%s\t%s\n' "$m" "$(on_role "$m" 'cat /proc/loadavg' 2>/dev/null || true)" >> "$RUN_DIR/load.tsv"
done

echo "--- Network between machines (RTT, 10 pings) ---"
: > "$RUN_DIR/network.tsv"
for from in $(machines); do
  for to in $(machines); do
    [[ "$from" == "$to" ]] && continue
    v="$(rtt_ms "$from" "$(host_of_role "$to")")"
    printf '%s\t%s\t%s\n' "$from" "$to" "${v:-}" >> "$RUN_DIR/network.tsv"
    printf '  %-9s → %-9s %s ms\n' "$from" "$to" "${v:-?}"
  done
done

# ── Setup (idempotent; also corrects asset addresses after a move) ────────────
bash "$SCRIPT_DIR/1-setup-provider.sh" > "$RUN_DIR/setup.out" 2>&1 \
  || { cat "$RUN_DIR/setup.out"; exit 1; }
sleep 3

echo "--- CPU/RAM at rest ---"
: > "$RUN_DIR/at-rest.txt"
for m in $(machines); do
  cs="$(containers_on "$m")"
  # shellcheck disable=SC2086
  [[ -n "$cs" ]] && sample_stats_on "$m" $cs | tee -a "$RUN_DIR/at-rest.txt"
done

# ── Test cases ────────────────────────────────────────────────────────────────
for tc in $TCS; do
  echo ""
  echo "================================================================"
  echo " $tc"
  echo "================================================================"
  record_clocks "before-$tc"
  curl -sf -X POST "$RECEIVER_BASE/reset" > /dev/null

  MON_PIDS=()
  for m in $(machines); do
    cs="$(containers_on "$m")"
    # shellcheck disable=SC2086
    [[ -n "$cs" ]] && MON_PIDS+=("$(start_stats_monitor_on "$m" "$RUN_DIR/stats-$tc-$m.txt" $cs)")
  done

  exit_code=0
  LINKCUT_PID=""
  TC_START_ISO="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  if [[ "$tc" == pull-timed-linkcut ]]; then
    cp_host="$(host_of_role "$PROVIDER_CP_ROLE")"
    [[ "$cp_host" != "$(host_of_role "$PROVIDER_DP_ROLE")" ]] \
      || { echo "pull-timed-linkcut needs the provider's planes on different machines" >&2; exit 1; }
    on_role "$PROVIDER_DP_ROLE" "bash scripts/link-cut.sh $cp_host ${LINK_CUT_AT:-20} ${LINK_CUT_FOR:-70}" \
      > "$RUN_DIR/linkcut-$tc.txt" 2>&1 &
    LINKCUT_PID=$!
  fi
  if [[ "$tc" == s[0-9]* ]]; then   # payload sweep, e.g. s1048576
    run_tc_script "$SCRIPT_DIR/6-payload-sweep.sh" "${tc#s}" 2>&1 | tee "$RUN_DIR/$tc.out" || exit_code=$?
  elif [[ "$tc" == pull-* ]]; then  # PULL transfer, e.g. pull-tc1, pull-s1048576
    run_tc_script "$SCRIPT_DIR/7-pull-transfer.sh" "$tc" 2>&1 | tee "$RUN_DIR/$tc.out" || exit_code=$?
  else
    run_tc_script "$(tc_script "$tc")" 2>&1 | tee "$RUN_DIR/$tc.out" || exit_code=$?
  fi
  printf 'exit\t%s\t%s\n' "$tc" "$exit_code" >> "$RUN_LOG"
  if [[ -n "$LINKCUT_PID" ]]; then
    wait "$LINKCUT_PID" || true
    # no DROP rule for the Control Plane's machine may outlive the test case
    left="$(on_role "$PROVIDER_DP_ROLE" "iptables -S | grep -c -- '$cp_host.* -j DROP' || true")"
    if [[ "${left:-0}" != 0 ]]; then
      echo "  ! $left link-cut rule(s) left on $PROVIDER_DP_ROLE — removing" >&2
      on_role "$PROVIDER_DP_ROLE" "for c in INPUT OUTPUT DOCKER-USER; do for d in -s -d; do while iptables -D \$c \$d $cp_host -j DROP 2>/dev/null; do :; done; done; done"
    fi
    cat "$RUN_DIR/linkcut-$tc.txt"
    # Review re-run A (27 Oct 2026): keep the provider planes' logs and their
    # transfer records, which show when the CP's termination reached the DP
    # (each on its own machine's clock; offsets in the run's clock records).
    on_role "$PROVIDER_CP_ROLE" "docker logs --timestamps --since $TC_START_ISO provider-cp 2>&1" > "$RUN_DIR/log-provider-cp-$tc.txt" || true
    on_role "$PROVIDER_DP_ROLE" "docker logs --timestamps --since $TC_START_ISO provider-dp 2>&1" > "$RUN_DIR/log-provider-dp-$tc.txt" || true
    on_role "$PROVIDER_CP_ROLE" "docker exec provider-cp-db psql -U edc -d provider_cp -Atc 'select row_to_json(t) from edc_transfer_process t'" > "$RUN_DIR/db-provider-cp-transfers-$tc.jsonl" || true
    on_role "$PROVIDER_DP_ROLE" "docker exec provider-dp-db psql -U edc -d provider_dp -Atc 'select row_to_json(t) from edc_data_plane t'" > "$RUN_DIR/db-provider-dp-flows-$tc.jsonl" || true
    on_role "$PROVIDER_DP_ROLE" "docker exec provider-dp-db psql -U edc -d provider_dp -Atc 'select row_to_json(t) from edc_accesstokendata t'" > "$RUN_DIR/db-provider-dp-tokens-$tc.jsonl" || true
  fi

  stop_monitors

  curl -sf "$RECEIVER_BASE/metrics/$tc" > "$RUN_DIR/receiver-$tc.json" || echo '{}' > "$RUN_DIR/receiver-$tc.json"

  # Creation time of each transfer on consumer-cp — same machine and clock as
  # the receiver, so request→received needs no clock correction.
  ids="$(awk -F'\t' -v tc="$tc" '$1=="transfer" && $2==tc {printf "%s'\''%s'\''", (n++ ? "," : ""), $4}' "$RUN_LOG")"
  if [[ -n "$ids" ]]; then
    on_role consumer "docker exec consumer-cp-db psql -U edc -d consumer_cp -Atc \"select transferprocess_id || '|' || created_at || '|' || state from edc_transfer_process where transferprocess_id in ($ids)\"" \
      > "$RUN_DIR/created-$tc.tsv" || true
    # Provider side, for the phase breakdown in summarize-run.py: when the
    # provider's CP accepted each request (its record carries the consumer's
    # id as correlation_id), and when the DP received the start signal (its
    # data flow carries the provider's transfer id). Each on its own clock.
    on_role "$PROVIDER_CP_ROLE" "docker exec provider-cp-db psql -U edc -d provider_cp -Atc \"select correlation_id || '|' || transferprocess_id || '|' || created_at from edc_transfer_process where correlation_id in ($ids)\"" \
      > "$RUN_DIR/provider-cp-$tc.tsv" || true
    on_role "$PROVIDER_DP_ROLE" "docker exec provider-dp-db psql -U edc -d provider_dp -Atc \"select process_id || '|' || created_at from edc_data_plane\"" \
      > "$RUN_DIR/provider-dp-$tc.tsv" || true
  fi
  record_clocks "after-$tc"
done

echo ""
python3 "$SCRIPT_DIR/summarize-run.py" "$RUN_DIR"
