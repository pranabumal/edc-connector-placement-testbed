#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# negotiation-race.sh <arch> <timing> [count]
# Deploys <arch> with timing profile <timing> (deploy/timing/<timing>.env) on
# every machine, from empty databases, then runs <count> (default 20) contract
# negotiations one after another and records how each ended.
#
# Checks whether a timing profile triggers EDC's agreement-verification race
# (provider answers 409, consumer terminates the negotiation). Durations come
# from the consumer Control Plane's own timestamps (created → finalized), not
# from polling, so they are accurate to the millisecond.
#
# Output: results/<ts>-negrace-<arch>-<timing>/negotiations.tsv
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

ARCH="${1:?usage: negotiation-race.sh <arch> <timing> [count]}"
TIMING="${2:?usage: negotiation-race.sh <arch> <timing> [count]}"
COUNT="${3:-20}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OUT="$REPO_ROOT/results/$(date +%Y%m%dT%H%M%S)-negrace-$ARCH-$TIMING"
mkdir -p "$OUT"

[[ "${NO_SYNC:-0}" == 1 ]] || bash "$REPO_ROOT/deploy/sync.sh"
bash "$REPO_ROOT/deploy/deploy.sh" "$ARCH" --timing "$TIMING" endpoints > /dev/null
# shellcheck source=./lib-remote.sh
source "$SCRIPT_DIR/lib-remote.sh"
for m in $(machines); do
  echo "--- deploy on $(roles_on_machine "$m") ---"
  ON_ROLE_TIMEOUT=1800 on_role "$m" "bash deploy/deploy.sh $ARCH --timing $TIMING --wipe 2>&1" | grep -E '^(Architecture|▶|■)|rror' || true
done
bash "$REPO_ROOT/deploy/deploy.sh" "$ARCH" --timing "$TIMING" endpoints > /dev/null
cp "$REPO_ROOT/deploy/.endpoints.env" "$OUT/endpoints.env"

# shellcheck source=./lib-endpoints.sh
source "$SCRIPT_DIR/lib-endpoints.sh"
for _ in $(seq 1 60); do curl -s -o /dev/null "$PROVIDER_MGMT/assets" && break; sleep 3; done
sleep 10
bash "$SCRIPT_DIR/1-setup-provider.sh" > "$OUT/setup.out" 2>&1

ASSET_ID="asset-tc1-control"
OFFER_ID=$(curl -sf -X POST "$CONSUMER_MGMT/catalog/request" -H "Content-Type: application/json" -d "{
    \"@context\": { \"@vocab\": \"https://w3id.org/edc/v0.0.1/ns/\" },
    \"counterPartyAddress\": \"$PROVIDER_DSP\", \"protocol\": \"dataspace-protocol-http\" }" \
  | jq -r '.["dcat:dataset"] | if type == "array" then .[] else . end
           | select(.["@id"] == "'"$ASSET_ID"'") | .["odrl:hasPolicy"]["@id"]' | head -1)
[[ -n "$OFFER_ID" && "$OFFER_ID" != null ]] || { echo "no offer for $ASSET_ID"; exit 1; }

echo "--- $COUNT negotiations ($ARCH, $TIMING) ---"
IDS=()
for i in $(seq 1 "$COUNT"); do
  NEG_ID=$(curl -sf -X POST "$CONSUMER_MGMT/contractnegotiations" -H "Content-Type: application/json" -d "{
      \"@context\": { \"@vocab\": \"https://w3id.org/edc/v0.0.1/ns/\" }, \"@type\": \"ContractRequest\",
      \"counterPartyAddress\": \"$PROVIDER_DSP\", \"protocol\": \"dataspace-protocol-http\",
      \"policy\": { \"@context\": \"http://www.w3.org/ns/odrl.jsonld\", \"@id\": \"$OFFER_ID\",
                    \"@type\": \"Offer\", \"assigner\": \"provider\", \"target\": \"$ASSET_ID\" } }" | jq -r '.["@id"]')
  IDS+=("$NEG_ID")
  STATE=""
  for _ in $(seq 1 300); do   # up to 30 s
    sleep 0.1
    STATUS=$(curl -sf "$CONSUMER_MGMT/contractnegotiations/$NEG_ID")
    STATE=$(echo "$STATUS" | jq -r '.state')
    [[ "$STATE" == FINALIZED || "$STATE" == TERMINATED ]] && break
  done
  echo "  $i  $NEG_ID  $STATE"
  # The consumer's record of a failure may hold no error text; keep what the API says.
  [[ "$STATE" == FINALIZED ]] || echo "$STATUS" >> "$OUT/failed.jsonl"
  sleep 0.5
done

# Durations and errors from the consumer's own records (state 1200 = FINALIZED, 1400 = TERMINATED)
in_list=$(printf "'%s'," "${IDS[@]}"); in_list="${in_list%,}"
printf 'negotiation_id\tstate\tduration_ms\terror_detail\n' > "$OUT/negotiations.tsv"
on_role consumer "docker exec consumer-cp-db psql -U edc -d consumer_cp -AtF \$'\\t' -c \"select id, case state when 1200 then 'FINALIZED' when 1400 then 'TERMINATED' else state::text end, state_timestamp - created_at, coalesce(replace(error_detail, E'\\n', ' '), '') from edc_contract_negotiation where id in ($in_list) order by created_at\"" >> "$OUT/negotiations.tsv"

python3 - "$OUT/negotiations.tsv" <<'EOF'
import csv, statistics, sys
rows = list(csv.DictReader(open(sys.argv[1]), delimiter="\t"))
ok = [int(r["duration_ms"]) for r in rows if r["state"] == "FINALIZED"]
bad = [r for r in rows if r["state"] != "FINALIZED"]
print(f"\nfinalized {len(ok)} of {len(rows)}, failed {len(bad)}")
if ok:
    print(f"duration ms: median {statistics.median(ok):.0f}, min {min(ok)}, max {max(ok)}")
for r in bad:
    print(f"  {r['state']}: {r['error_detail'][:200]}")
EOF
echo "Results: $OUT"
