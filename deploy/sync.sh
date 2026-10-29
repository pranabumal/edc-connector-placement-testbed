#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# sync.sh — copy this working copy to every remote machine in hosts.env
# (each role with a *_SSH entry), into ~/$REMOTE_DIR (default: the
# same folder name as here).
#
# Build output, .git, results and per-machine state (secrets.env,
# .endpoints.env) are not copied; hosts.env is, so every machine shares it.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=../scripts/lib-remote.sh
source "$REPO_ROOT/scripts/lib-remote.sh"
[[ "$DISTRIBUTED" == 1 ]] || { echo "sync.sh: no deploy/hosts.env + .endpoints.env — nothing to sync to"; exit 0; }

done_hosts=" "
for role in $ROLES; do
  ssh_args="$(ssh_of_role "$role")"
  [[ -z "$ssh_args" ]] && continue                     # this machine
  target="${ssh_args%% *}"                              # user@host
  opts="${ssh_args#"$target"}"                          # e.g. -i ~/.ssh/key
  [[ "$done_hosts" == *" $target "* ]] && continue
  done_hosts="$done_hosts$target "
  echo "→ $target ($(roles_on_machine "$role"))"
  rsync -az --delete \
    --exclude .git --exclude build/ --exclude bin/ --exclude node_modules/ --exclude .gradle/ \
    --exclude /results/ --exclude __pycache__/ --exclude .DS_Store \
    --exclude deploy/secrets.env --exclude deploy/.endpoints.env \
    -e "ssh -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=10 -o ServerAliveInterval=10 -o ServerAliveCountMax=3$opts" \
    "$REPO_ROOT/" "$target:$REMOTE_DIR/"
done
