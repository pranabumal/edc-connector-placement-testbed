#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# deploy.sh — start/stop the units that belong on THIS machine for a given
# architecture.
#
#   deploy/deploy.sh <arch> [up|down|ps]            roles detected from this
#                                                   machine's IP addresses
#   deploy/deploy.sh <arch> --on edge,source ...    roles given explicitly
#   deploy/deploy.sh <arch> --local        ...      every role on this machine
#
#   <arch>   cloud | edge | hybrid   (deploy/arch/<arch>.env: where the
#            provider's Control Plane and Data Plane run)
#   roles    edge | source | cloud | consumer   (machines in deploy/hosts.env)
#   --timing default | tuned   (deploy/timing/<name>.env: EDC state-machine
#            wait on every connector; use the same one on every machine)
#   --wipe   with `down`: also delete the units' databases
#            with `up`: start the connector units from empty databases
#   endpoints  only (re)write deploy/.endpoints.env — for a machine that runs
#            the tests but plays no role
#
# Run it on every machine with the same <arch>. Units that belonged here under
# a previous architecture are stopped (data kept), so switching is one command
# per machine. Each machine's provider-cp-db is its own, so after provider-cp
# moves, re-run scripts/1-setup-provider.sh.
#
# Writes deploy/.endpoints.env, which the test scripts read.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

DEPLOY_DIR="$(cd "$(dirname "$0")" && pwd)"
ROLES="edge source cloud consumer"
# Start order: data source, then data planes before the control planes that
# register them, dashboard last.
UNITS="provider-source provider-dp provider-cp consumer-dp consumer-cp dashboard"

die() { echo "deploy.sh: $*" >&2; exit 1; }
usage() { sed -n '3,22p' "$0" | sed 's/^# \{0,1\}//'; exit 1; }
upper() { echo "$1" | tr '[:lower:]' '[:upper:]'; }
is_ipv4() { [[ "$1" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; }

# ── Arguments ────────────────────────────────────────────────────────────────
[[ $# -ge 1 ]] || usage
ARCH="$1"; shift
ON=""; LOCAL=0; WIPE=0; ACTION="up"; TIMING="default"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --on)    ON="${2:-}"; shift 2 ;;
    --local) LOCAL=1; shift ;;
    --wipe)  WIPE=1; shift ;;
    --timing) TIMING="${2:-}"; shift 2 ;;
    up|down|ps|endpoints) ACTION="$1"; shift ;;
    -h|--help) usage ;;
    *) die "unknown argument: $1" ;;
  esac
done

ARCH_FILE="$DEPLOY_DIR/arch/$ARCH.env"
[[ -f "$ARCH_FILE" ]] || die "no architecture '$ARCH' (have: $(ls "$DEPLOY_DIR/arch" | sed 's/\.env$//' | tr '\n' ' '))"

TIMING_FILE="$DEPLOY_DIR/timing/$TIMING.env"
[[ -f "$TIMING_FILE" ]] || die "no timing profile '$TIMING' (have: $(ls "$DEPLOY_DIR/timing" | sed 's/\.env$//' | tr '\n' ' '))"

# ── Machines and architecture ────────────────────────────────────────────────
if [[ -f "$DEPLOY_DIR/hosts.env" ]]; then
  # shellcheck disable=SC1091
  source "$DEPLOY_DIR/hosts.env"
elif [[ $LOCAL -eq 0 ]]; then
  die "deploy/hosts.env missing — copy deploy/hosts.env.example and fill it in"
fi
# shellcheck disable=SC1090
source "$ARCH_FILE"
# shellcheck disable=SC1090
source "$TIMING_FILE"

# Timing profile → JVM system properties for every EDC runtime (passed through
# JAVA_TOOL_OPTIONS in units/common.yaml; the JVM logs them at startup). The
# keys are EDC's own; a runtime ignores the ones it has no state machine for.
EDC_JAVA_OPTS=""
if [[ -n "${EDC_TRANSFER_WAIT_MS:-}" ]]; then
  for key in edc.transfer.state-machine edc.dataplane.state-machine; do
    EDC_JAVA_OPTS="$EDC_JAVA_OPTS -D$key.iteration-wait-millis=$EDC_TRANSFER_WAIT_MS"
  done
fi
if [[ -n "${EDC_NEGOTIATION_WAIT_MS:-}" ]]; then
  for key in edc.negotiation.state-machine edc.negotiation.consumer.state-machine \
             edc.negotiation.provider.state-machine; do
    EDC_JAVA_OPTS="$EDC_JAVA_OPTS -D$key.iteration-wait-millis=$EDC_NEGOTIATION_WAIT_MS"
  done
fi
# Provider side of the negotiation only (the consumer keeps its own wait).
if [[ -n "${EDC_PROVIDER_NEGOTIATION_WAIT_MS:-}" ]]; then
  EDC_JAVA_OPTS="$EDC_JAVA_OPTS -Dedc.negotiation.provider.state-machine.iteration-wait-millis=$EDC_PROVIDER_NEGOTIATION_WAIT_MS"
fi
export EDC_JAVA_OPTS
export DB_SYNCHRONOUS_COMMIT="${DB_SYNCHRONOUS_COMMIT:-on}"

: "${EDGE_CPU:=1.0}" "${EDGE_MEM:=1024m}"
: "${CLOUD_CPU:=4.0}" "${CLOUD_MEM:=4096m}"
: "${CONSUMER_CPU:=4.0}" "${CONSUMER_MEM:=4096m}"
: "${DASHBOARD_ROLE:=edge}"

if [[ $LOCAL -eq 1 ]]; then
  [[ -z "$ON" ]] || die "--local and --on are exclusive"
  SELF_IP="${LOCAL_HOST:-$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}')}"
  [[ -n "$SELF_IP" ]] || die "could not detect this machine's IP; set LOCAL_HOST=<ip>"
  for r in $ROLES; do
    eval "$(upper "$r")_HOST=\$SELF_IP"
    eval "$(upper "$r")_BIND=0.0.0.0"
  done
  ON="$(echo $ROLES | tr ' ' ',')"
fi

for r in $ROLES; do
  v="$(upper "$r")_HOST"
  [[ -n "${!v:-}" ]] || die "$v not set in hosts.env"
done

host_of() { local v; v="$(upper "$1")_HOST"; echo "${!v}"; }
bind_of() {
  local v h; v="$(upper "$1")_BIND"; h="$(host_of "$1")"
  if [[ -n "${!v:-}" ]]; then echo "${!v}"; elif is_ipv4 "$h"; then echo "$h"; else echo "0.0.0.0"; fi
}

# ── Which roles does this machine play? ──────────────────────────────────────
if [[ -z "$ON" && "$ACTION" == "endpoints" ]]; then
  ON="none"
elif [[ -z "$ON" ]]; then
  # Every address this machine answers to: Tailscale, interfaces, hostname.
  SELF_ADDRS=" $( { tailscale ip -4 2>/dev/null; hostname -I 2>/dev/null | tr ' ' '\n';
                   ifconfig 2>/dev/null | awk '/inet /{print $2}'; hostname; hostname -s; } | tr '\n' ' ') "
  for r in $ROLES; do
    [[ "$SELF_ADDRS" == *" $(host_of "$r") "* ]] && ON="${ON:+$ON,}$r"
  done
  [[ -n "$ON" ]] || die "this machine matches no role in hosts.env — pass --on <role>[,<role>]"
fi
for r in ${ON//,/ }; do [[ "$r" == none || " $ROLES " == *" $r "* ]] || die "unknown role '$r' (roles: $ROLES)"; done
plays() { [[ ",$ON," == *",$1,"* ]]; }

role_of() {
  case "$1" in
    provider-source)         echo source ;;
    provider-dp)             echo "$PROVIDER_DP_TIER" ;;
    provider-cp)             echo "$PROVIDER_CP_TIER" ;;
    consumer-cp|consumer-dp) echo consumer ;;
    dashboard)               echo "$DASHBOARD_ROLE" ;;
  esac
}

SOURCE_HOST="$(host_of source)"
PROVIDER_CP_HOST="$(host_of "$(role_of provider-cp)")"
PROVIDER_DP_HOST="$(host_of "$(role_of provider-dp)")"
CONSUMER_CP_HOST="$(host_of consumer)"
CONSUMER_DP_HOST="$(host_of consumer)"
export SOURCE_HOST PROVIDER_CP_HOST PROVIDER_DP_HOST CONSUMER_CP_HOST CONSUMER_DP_HOST

# ── Database password (per machine; each DB is only reached on its own host) ─
SECRETS="$DEPLOY_DIR/secrets.env"
if [[ ! -f "$SECRETS" ]]; then
  umask 077
  echo "DB_PASSWORD=$(openssl rand -hex 16)" > "$SECRETS"
  echo "Generated $SECRETS"
fi
# shellcheck disable=SC1090
source "$SECRETS"
export DB_PASSWORD

# ── Endpoints for the test scripts ───────────────────────────────────────────
cat > "$DEPLOY_DIR/.endpoints.env" <<EOF
# Generated by deploy/deploy.sh $(date -u +%Y-%m-%dT%H:%M:%SZ) — do not edit
ARCH=$ARCH
TIMING=$TIMING
EDC_TRANSFER_WAIT_MS=${EDC_TRANSFER_WAIT_MS:-}
EDC_NEGOTIATION_WAIT_MS=${EDC_NEGOTIATION_WAIT_MS:-}
EDC_PROVIDER_NEGOTIATION_WAIT_MS=${EDC_PROVIDER_NEGOTIATION_WAIT_MS:-}
PROVIDER_CP_ROLE=$(role_of provider-cp)
PROVIDER_DP_ROLE=$(role_of provider-dp)
SOURCE_HOST=$SOURCE_HOST
PROVIDER_CP_HOST=$PROVIDER_CP_HOST
PROVIDER_DP_HOST=$PROVIDER_DP_HOST
CONSUMER_CP_HOST=$CONSUMER_CP_HOST
CONSUMER_DP_HOST=$CONSUMER_DP_HOST
EOF

if [[ "$ACTION" == "endpoints" ]]; then
  echo "Wrote $DEPLOY_DIR/.endpoints.env for '$ARCH'"
  exit 0
fi

# ── Guard: the single-machine stack uses the same container names ───────────
if [[ "$ACTION" == "up" ]] && [[ -n "$(docker ps -aq --filter label=com.docker.compose.project=docker)" ]]; then
  die "the single-machine stack (docker/docker-compose.yaml) is still present — run: docker compose -f docker/docker-compose.yaml down"
fi

compose() { docker compose -f "$DEPLOY_DIR/units/$1/docker-compose.yaml" "${@:2}"; }

echo "Architecture: $ARCH    timing: $TIMING    this machine: $ON"
for unit in $UNITS; do
  printf '  %-16s %-9s %s\n' "$unit" "$(role_of "$unit")" "$(host_of "$(role_of "$unit")")"
done
echo ""

for unit in $UNITS; do
  role="$(role_of "$unit")"
  if plays "$role"; then
    case "$role" in
      edge)     export UNIT_CPU="$EDGE_CPU"     UNIT_MEM="$EDGE_MEM" ;;
      cloud)    export UNIT_CPU="$CLOUD_CPU"    UNIT_MEM="$CLOUD_MEM" ;;
      consumer) export UNIT_CPU="$CONSUMER_CPU" UNIT_MEM="$CONSUMER_MEM" ;;
      *)        export UNIT_CPU="1.0"           UNIT_MEM="1024m" ;;   # not a connector unit
    esac
    export BIND_ADDR; BIND_ADDR="$(bind_of "$role")"
    case "$ACTION" in
      up)   echo "▶ $unit ($role, ${UNIT_CPU} CPU / ${UNIT_MEM}, ports on ${BIND_ADDR})"
            # Connector units only: the data source keeps its AAS content.
            if [[ $WIPE -eq 1 && "$unit" == *-[cd]p ]]; then compose "$unit" down -v; fi
            compose "$unit" up -d --build --remove-orphans ;;
      down) echo "■ $unit"; if [[ $WIPE -eq 1 ]]; then compose "$unit" down -v; else compose "$unit" down; fi ;;
      ps)   compose "$unit" ps ;;
    esac
  elif [[ "$ACTION" != "ps" ]] && [[ -n "$(docker ps -aq --filter label=com.docker.compose.project="$unit")" ]]; then
    # Left over from a previous architecture — not this machine's job any more.
    echo "■ $unit (not on this machine under '$ARCH')"
    UNIT_CPU=1 UNIT_MEM=1g BIND_ADDR=0.0.0.0 compose "$unit" down
  fi
done
