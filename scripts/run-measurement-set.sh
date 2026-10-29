#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# run-measurement-set.sh <A|B|C|D|S> [architecture ...]
# One measurement set of the thesis protocol (thesis Chapter 3),
# distributed testbed only. For each
# architecture: sync is done once, then deploy with empty databases, wait for
# the provider's Control Plane, and run run-all-tests.sh with the set's
# settings. Runs land in results/<timestamp>-<arch>-<timing>-<set tag>/.
#
#   A  push, TC-1..TC-3 × 20 transfers, tuned-nosync; three repeats in
#      alternating order (hybrid edge cloud / edge cloud hybrid /
#      cloud hybrid edge). Architectures given on the command line replace
#      that order (one repeat).
#   B  pull at the target rates (TC-1 50 Hz, TC-2 1/s, TC-3 24 Hz) for
#      PULL_DURATION s (default 300), tuned-nosync, per architecture:
#      B-seq one worker, B-par PAR_WORKERS workers (default 4), B-src the
#      baseline straight from the data source (no EDC).
#   C  EDC defaults (1000 ms waits, database sync on): push TC-1..TC-3 × 20.
#   D  enforcement, tuned-nosync, TC-1's data, contracts valid 45 s:
#      D-enf per architecture: no token / wrong token, provider terminates
#      a running transfer, contract expiry during fetching (every 0.1 s);
#      D-linkcut on hybrid only: expiry while the link between the provider's
#      Control Plane (cloud) and Data Plane (edge) is cut.
#   S  payload sweep (push), tuned-nosync, on hybrid unless given.
#
# NO_SYNC=1 skips copying the code to the machines. B_RUNS (default
# "seq par src") and D_RUNS (default "enf linkcut") pick runs of sets B and D,
# to repeat only those a network outage spoiled.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SET="${1:?usage: run-measurement-set.sh A|B|C|D|S [architecture ...]}"; shift
[[ -f "$REPO_ROOT/deploy/hosts.env" ]] || { echo "needs deploy/hosts.env (distributed testbed)" >&2; exit 1; }

deploy() {   # deploy <arch> <timing>
  local arch="$1" timing="$2" m
  echo ""
  echo "================================================================"
  echo " Set $SET — deploying $arch ($timing)   $(date)"
  echo "================================================================"
  bash "$REPO_ROOT/deploy/deploy.sh" "$arch" --timing "$timing" endpoints > /dev/null
  # shellcheck source=./lib-remote.sh
  source "$SCRIPT_DIR/lib-remote.sh"
  for m in $(machines); do
    echo "--- deploy on $(roles_on_machine "$m") ($(host_of_role "$m")) ---"
    ON_ROLE_TIMEOUT=1800 on_role "$m" "bash deploy/deploy.sh $arch --timing $timing --wipe 2>&1" | grep -E '^(Architecture|▶|■)|rror' || true
  done
  bash "$REPO_ROOT/deploy/deploy.sh" "$arch" --timing "$timing" endpoints > /dev/null
  # shellcheck source=./lib-endpoints.sh
  source "$SCRIPT_DIR/lib-endpoints.sh"
  local up=0
  for _ in $(seq 1 60); do
    curl -s -o /dev/null "$PROVIDER_MGMT/assets" && { up=1; break; }
    sleep 3
  done
  [[ "$up" == 1 ]] || { echo "provider Control Plane did not come up" >&2; exit 1; }
  # Ready = the consumer gets the provider's catalogue over DSP (the Management
  # API can answer before the protocol endpoint does: Edge A-r1, 2026-10-22).
  up=0
  for _ in $(seq 1 30); do
    curl -sf -o /dev/null -X POST "$CONSUMER_MGMT/catalog/request" -H "Content-Type: application/json" \
      -d "{\"@context\": {\"@vocab\": \"https://w3id.org/edc/v0.0.1/ns/\"}, \"counterPartyAddress\": \"$PROVIDER_DSP\", \"protocol\": \"dataspace-protocol-http\"}" \
      && { up=1; break; }
    sleep 3
  done
  [[ "$up" == 1 ]] || { echo "consumer cannot get the provider's catalogue" >&2; exit 1; }
  sleep 10   # let the CP register its Data Plane before the first transfer
}

run() {      # run <arch> <tag> [VAR=value ...]
  local arch="$1" tag="$2"; shift 2
  env "$@" ARCH_LABEL="$arch" RUN_TAG="$tag" MEASUREMENT_SET="$SET" bash "$SCRIPT_DIR/run-all-tests.sh"
}

[[ "${NO_SYNC:-0}" == 1 ]] || { echo "--- Syncing code to the other machines ---"; bash "$REPO_ROOT/deploy/sync.sh"; }

PUSH20=(TC1_REPEAT=20 TC2_REPEAT=20 TC3_REPEAT=20 "TCS=tc1 tc2 tc3")
case "$SET" in
  A)
    if [[ $# -gt 0 ]]; then orders=("$*"); else
      orders=("hybrid edge cloud" "edge cloud hybrid" "cloud hybrid edge"); fi
    r=$(( ${A_REPEAT_FROM:-1} - 1 ))   # A_REPEAT_FROM: number of the first repeat (tags A-r<n>)
    for order in "${orders[@]}"; do
      r=$((r + 1))
      for arch in $order; do
        deploy "$arch" tuned-nosync
        run "$arch" "A-r$r" "${PUSH20[@]}"
      done
    done ;;
  B)
    [[ $# -gt 0 ]] || set -- hybrid edge cloud
    PULL3=("TCS=pull-tc1 pull-tc2 pull-tc3" PULL_RATE=target PULL_DURATION="${PULL_DURATION:-300}")
    for arch in "$@"; do
      deploy "$arch" tuned-nosync
      B=" ${B_RUNS:-seq par src} "
      if [[ "$B" == *" seq "* ]]; then run "$arch" B-seq "${PULL3[@]}" PULL_PARALLEL=1; fi
      if [[ "$B" == *" par "* ]]; then run "$arch" B-par "${PULL3[@]}" PULL_PARALLEL="${PAR_WORKERS:-4}"; fi
      if [[ "$B" == *" src "* ]]; then run "$arch" B-src "${PULL3[@]}" PULL_PARALLEL=1 PULL_VIA=source; fi
    done ;;
  C)
    [[ $# -gt 0 ]] || set -- hybrid edge cloud
    for arch in "$@"; do
      deploy "$arch" default
      run "$arch" C-default "${PUSH20[@]}"
    done ;;
  D)
    [[ $# -gt 0 ]] || set -- hybrid edge cloud
    ENF=(POLICY_VALID_S=45 TIMED_INTERVAL_S=0.1)
    for arch in "$@"; do
      deploy "$arch" tuned-nosync
      D=" ${D_RUNS:-enf linkcut} "
      if [[ "$D" == *" enf "* ]]; then run "$arch" D-enf "TCS=pull-tokens pull-terminate pull-timed" "${ENF[@]}"; fi
      if [[ "$arch" == hybrid && "$D" == *" linkcut "* ]]; then
        # cut 20 s into the test case (contract signed by then), restore 70 s
        # later — after expiry (~45 s after signing); fetch 60 s past expiry
        run "$arch" D-linkcut "TCS=pull-timed-linkcut" "${ENF[@]}" TIMED_AFTER_S=60 LINK_CUT_AT=20 LINK_CUT_FOR=70
      fi
    done ;;
  S)
    [[ $# -gt 0 ]] || set -- hybrid
    for arch in "$@"; do
      deploy "$arch" tuned-nosync
      run "$arch" S-sweep "TCS=${SWEEP_TCS:-s10240 s1048576 s10485760 s52428800}"
    done ;;
  X)
    # Diagnostic, not a protocol set (26 Oct 2026): why TC3 pull through the
    # edge Data Plane is slow. TC3 at 24 Hz for 120 s, one worker, once with
    # one kept-alive connection (as in Set B) and once with a new connection
    # per fetch, while diag-monitor.sh records TCP and CPU on the DP machine.
    [[ $# -gt 0 ]] || set -- edge cloud
    for arch in "$@"; do
      deploy "$arch" tuned-nosync
      for mode in keep new; do
        nc=0; if [[ "$mode" == new ]]; then nc=1; fi
        ON_ROLE_TIMEOUT=400 on_role "$PROVIDER_DP_ROLE" "bash scripts/diag-monitor.sh 240 /tmp/diag-$mode" > /dev/null 2>&1 &
        mon=$!
        run "$arch" "X-$mode" "TCS=pull-tc3" PULL_RATE=target PULL_DURATION=120 PULL_PARALLEL=1 PULL_NEW_CONN="$nc"
        wait "$mon" || true
        d="$(ls -dt "$REPO_ROOT"/results/*-"$arch"-tuned-nosync-X-"$mode" | head -1)"
        on_role "$PROVIDER_DP_ROLE" "cat /tmp/diag-$mode-ss.txt" > "$d/diag-ss.txt" || true
        on_role "$PROVIDER_DP_ROLE" "cat /tmp/diag-$mode-vmstat.txt" > "$d/diag-vmstat.txt" || true
      done
    done ;;
  R)
    # Review re-runs (27 Oct 2026), supplementary to the protocol runs of
    # 22 Oct; R_RUNS picks them (default "linkcut push1hz pulldef"):
    #   linkcut  Hybrid, three link cuts that start 28, 18 and 8 s before the
    #            contract expires (cut at 20/30/40 s for 70/45/25 s), with the
    #            provider planes' logs and transfer records (run-all-tests.sh)
    #   push1hz  TC2 push at 1 Hz for 300 s (PUSH_INTERVAL_S=1), per architecture
    #   pulldef  TC2 pull at 1 Hz for 300 s, one worker, EDC's default profile
    R=" ${R_RUNS:-linkcut push1hz pulldef} "
    ENF=(POLICY_VALID_S=45 TIMED_INTERVAL_S=0.1)
    if [[ "$R" == *" linkcut "* ]]; then
      for cut in "20 70" "30 45" "40 25"; do
        at="${cut% *}" for_s="${cut#* }"
        deploy hybrid tuned-nosync
        run hybrid "R-linkcut-at$at" "TCS=pull-timed-linkcut" "${ENF[@]}" TIMED_AFTER_S=60 LINK_CUT_AT="$at" LINK_CUT_FOR="$for_s"
      done
    fi
    for arch in ${R_ARCHS:-hybrid edge cloud}; do
      if [[ "$R" == *" push1hz "* ]]; then
        deploy "$arch" tuned-nosync
        run "$arch" R-push1hz "TCS=tc2" TC2_REPEAT=300 PUSH_INTERVAL_S=1
      fi
      if [[ "$R" == *" pulldef "* ]]; then
        deploy "$arch" default
        run "$arch" R-pulldef "TCS=pull-tc2" PULL_RATE=target PULL_DURATION=300 PULL_PARALLEL=1
      fi
    done ;;
  *) echo "unknown set '$SET' (A, B, C, D, R, S or X)" >&2; exit 1 ;;
esac
echo ""
echo "Set $SET done   $(date)"
