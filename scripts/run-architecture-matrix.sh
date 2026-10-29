#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# run-architecture-matrix.sh
# Runs the full TC-1..TC-4 suite (run-all-tests.sh) against each candidate
# architecture from Methods §3.3 — Cloud, Edge, Hybrid — and combines the runs
# into one test-case × architecture matrix (Methods Table 3.2).
#
# Distributed (deploy/hosts.env present): for each architecture, syncs the
# code to every machine, runs deploy/deploy.sh <arch> on each of them (the
# provider's planes move; data source and consumer stay), waits for the
# provider's Control Plane, then runs the suite. Each run lands in
# results/<timestamp>-<arch>/, the matrix in results/matrix-<timestamp>.json.
#
# Single machine (no hosts.env): the original emulation — one Docker Compose
# stack, architectures differing only in CPU/RAM limits.
#
# Distributed runs cover each architecture under each timing profile
# (deploy/timing/*.env) — by default EDC's own 1 s state-machine wait and a
# short one — so the matrix shows both what an adopter gets out of the box and
# what the placement itself costs.
#
# Usage:
#   bash scripts/run-architecture-matrix.sh                 # edge cloud hybrid
#   TIMINGS="default" bash scripts/run-architecture-matrix.sh   # one profile only
#   bash scripts/run-architecture-matrix.sh hybrid cloud     # subset, in order
#   NO_SYNC=1 bash scripts/run-architecture-matrix.sh        # skip code sync
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
RESULTS_DIR="${RESULTS_DIR:-$REPO_ROOT/results}"
mkdir -p "$RESULTS_DIR"

ARCHITECTURES=("$@")
[ ${#ARCHITECTURES[@]} -eq 0 ] && ARCHITECTURES=(edge cloud hybrid)

echo ""
echo "################################################################"
echo "#  Architecture Matrix Run — ${ARCHITECTURES[*]}"
echo "#  $(date)"
echo "################################################################"

RUN_DIRS=()
latest_run_dir() { ls -td "$RESULTS_DIR"/*-"$1" 2>/dev/null | head -1; }
TIMINGS="${TIMINGS:-default tuned}"

if [[ -f "$REPO_ROOT/deploy/hosts.env" ]]; then
  # ── Distributed ─────────────────────────────────────────────────────────────
  [[ "${NO_SYNC:-0}" == 1 ]] || { echo "--- Syncing code to the other machines ---"; bash "$REPO_ROOT/deploy/sync.sh"; }

  for arch in "${ARCHITECTURES[@]}"; do
   for timing in $TIMINGS; do
    echo ""
    echo "================================================================"
    echo " Architecture: $arch   timing: $timing"
    echo "================================================================"
    # Fresh endpoints for this architecture, then deploy on every machine.
    bash "$REPO_ROOT/deploy/deploy.sh" "$arch" --timing "$timing" endpoints > /dev/null
    # shellcheck source=./lib-remote.sh
    source "$SCRIPT_DIR/lib-remote.sh"
    for m in $(machines); do
      echo "--- deploy on $(roles_on_machine "$m") ($(host_of_role "$m")) ---"
      # --wipe: every run starts from empty connector databases. Transfers a
      # previous run left unfinished are otherwise retried by the next one
      # (against a Control Plane that may have moved) and slow it down.
      ON_ROLE_TIMEOUT=1800 on_role "$m" "bash deploy/deploy.sh $arch --timing $timing --wipe 2>&1" | grep -E '^(Architecture|▶|■)|rror' || true
    done
    # The local machine may play no role; re-assert this architecture's endpoints.
    bash "$REPO_ROOT/deploy/deploy.sh" "$arch" --timing "$timing" endpoints > /dev/null

    echo "--- Waiting for the provider's Control Plane ($PROVIDER_CP_HOST) ---"
    # shellcheck source=./lib-endpoints.sh
    source "$SCRIPT_DIR/lib-endpoints.sh"
    for _ in $(seq 1 60); do
      curl -s -o /dev/null "$PROVIDER_MGMT/assets" && break
      sleep 3
    done
    sleep 10   # let the CP register its Data Plane before the first transfer

    ARCH_LABEL="$arch" RESULTS_DIR="$RESULTS_DIR" bash "$SCRIPT_DIR/run-all-tests.sh"
    RUN_DIRS+=("$(latest_run_dir "$arch-$timing")")
   done
  done

else
  # ── Single machine: resource-tier emulation ─────────────────────────────────
  COMPOSE_FILE="$REPO_ROOT/docker/docker-compose.yaml"
  CORE_SERVICES=(provider-cp provider-dp consumer-cp consumer-dp simulator receiver)
  resources_for() {
    case "$1" in
      edge)   echo "1.0 1024m 1.0 1024m" ;;
      cloud)  echo "4 4096m 4 4096m" ;;
      hybrid) echo "4 4096m 1.0 1024m" ;;   # CP cloud tier / DP edge tier
      *) echo "ERROR: unknown architecture '$1' (expected edge|cloud|hybrid)" >&2; exit 1 ;;
    esac
  }
  for arch in "${ARCHITECTURES[@]}"; do
    read -r CP_CPU CP_MEM DP_CPU DP_MEM <<< "$(resources_for "$arch")"
    export CP_CPU CP_MEM DP_CPU DP_MEM
    echo ""
    echo "================================================================"
    echo " Architecture: $arch  (CP: ${CP_CPU} CPU / ${CP_MEM}, DP: ${DP_CPU} CPU / ${DP_MEM})"
    echo "================================================================"
    docker compose -f "$COMPOSE_FILE" down 2>&1 | tail -5
    docker compose -f "$COMPOSE_FILE" up -d --build "${CORE_SERVICES[@]}" 2>&1 | tail -20
    sleep 12
    ARCH_LABEL="$arch" RESULTS_DIR="$RESULTS_DIR" bash "$SCRIPT_DIR/run-all-tests.sh"
    RUN_DIRS+=("$(latest_run_dir "$arch-default")")
  done
  docker compose -f "$COMPOSE_FILE" down 2>&1 | tail -5
fi

# ── Test-case × architecture matrix ───────────────────────────────────────────
MATRIX_FILE="$RESULTS_DIR/matrix-$(date +%Y%m%dT%H%M%S).json"
echo ""
python3 "$SCRIPT_DIR/summarize-matrix.py" "$MATRIX_FILE" "${RUN_DIRS[@]}"
