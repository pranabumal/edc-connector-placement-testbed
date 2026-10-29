#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# link-cut.sh <peer-ip> <delay-s> <for-s>
# Measurement set D (Hybrid): cut the link between this machine — the host and
# its containers — and <peer-ip> (the provider's Control Plane machine) for
# <for-s> seconds, starting <delay-s> seconds from now. Every other link stays
# up: the consumer still reaches the Data Plane, the Data Plane its source.
#
# Run as root on the Data Plane's machine; run-all-tests.sh starts it there
# for pull-timed-linkcut. Prints the cut and restore times (unix s). The rules
# are removed when the script ends for any reason it can catch, and
# run-all-tests.sh checks afterwards that none is left.
# ─────────────────────────────────────────────────────────────────────────────
set -u
PEER="${1:?usage: link-cut.sh <peer-ip> <delay-s> <for-s>}" DELAY="${2:?}" FOR="${3:?}"
# host traffic (INPUT/OUTPUT) and container traffic, which is forwarded (DOCKER-USER)
RULES=("INPUT -s $PEER" "OUTPUT -d $PEER" "DOCKER-USER -s $PEER" "DOCKER-USER -d $PEER")

restore() {
  local r
  # shellcheck disable=SC2086  # each rule is deliberately word-split
  for r in "${RULES[@]}"; do while iptables -D $r -j DROP 2>/dev/null; do :; done; done
  echo "restored $(date +%s.%N)"
}
trap restore EXIT
trap 'exit 1' INT TERM HUP

sleep "$DELAY"
# shellcheck disable=SC2086
for r in "${RULES[@]}"; do iptables -I $r -j DROP; done
echo "cut $(date +%s.%N)"
sleep "$FOR"
