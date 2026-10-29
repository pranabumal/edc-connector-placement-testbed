#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# lib-remote.sh — run commands on the machine that plays a given role.
# Sourced by the measurement scripts (run-all-tests.sh, run-architecture-
# matrix.sh); defines functions only.
#
# Roles and their SSH access come from deploy/hosts.env (*_HOST, *_SSH). An
# empty *_SSH means "the machine running the tests". Without hosts.env (the
# single-machine stack) every role is this machine.
# ─────────────────────────────────────────────────────────────────────────────

_REMOTE_REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROLES="edge source cloud consumer"
# Folder of the project on the remote machines, relative to the SSH user's home
# (default: the same folder name as here).
REMOTE_DIR="${REMOTE_DIR:-$(basename "$_REMOTE_REPO_ROOT")}"

if [[ -f "$_REMOTE_REPO_ROOT/deploy/hosts.env" && -f "$_REMOTE_REPO_ROOT/deploy/.endpoints.env" \
      && "${IGNORE_ENDPOINTS_FILE:-0}" != "1" ]]; then
  # shellcheck disable=SC1091
  source "$_REMOTE_REPO_ROOT/deploy/hosts.env"
  # shellcheck disable=SC1091
  source "$_REMOTE_REPO_ROOT/deploy/.endpoints.env"
  DISTRIBUTED=1
else
  DISTRIBUTED=0
  for _r in $ROLES; do eval "$(echo "$_r" | tr '[:lower:]' '[:upper:]')_HOST=localhost"; done
  PROVIDER_CP_ROLE=edge
  PROVIDER_DP_ROLE=edge
  ARCH="${ARCH_LABEL:-single-machine}"
fi

_upper() { echo "$1" | tr '[:lower:]' '[:upper:]'; }
host_of_role() { local v; v="$(_upper "$1")_HOST"; echo "${!v}"; }
# MVD_LOCAL_ROLES: roles played by THIS machine although hosts.env gives them
# an ssh entry — set when a script is started on that role's machine by the
# test controller (run-all-tests.sh), so it does not ssh to itself.
ssh_of_role() {
  local v; v="$(_upper "$1")_SSH"
  [[ " ${MVD_LOCAL_ROLES:-} " == *" $1 "* ]] && return 0
  echo "${!v:-}"
}

# role_of_container <container> — which role's machine runs it, for the
# architecture deployed now (deploy/.endpoints.env)
role_of_container() {
  case "$1" in
    provider-cp|provider-cp-db) echo "$PROVIDER_CP_ROLE" ;;
    provider-dp|provider-dp-db) echo "$PROVIDER_DP_ROLE" ;;
    consumer-*|data-receiver)   echo consumer ;;
    data-simulator|basyx-*|crane-adapter) echo source ;;
    *) echo "unknown" ;;
  esac
}

# _with_timeout <seconds> <command...> — run it, killed after <seconds>; exit
# status 124 then (macOS has no timeout(1)). The timer stays in the parent:
# ssh resets an alarm it inherits, so one set before exec does not hold.
_with_timeout() {
  perl -e 'my $t = shift; my $pid = fork(); die "fork: $!\n" unless defined $pid;
           if (!$pid) { exec @ARGV or die "exec: $!\n" }
           my $late = 0;
           $SIG{ALRM} = sub { $late = 1; kill "TERM", $pid; sleep 2; kill "KILL", $pid };
           alarm $t; waitpid($pid, 0);
           exit($late ? 124 : ($? >> 8) || ($? & 127 ? 128 + ($? & 127) : 0))' "$@"
}

# on_role <role> <command string> — run in the project directory on that
# role's machine; stdout/stderr come back here. Ends after ON_ROLE_TIMEOUT
# seconds (default 900) whatever happens, so a machine that drops off the
# network mid-command fails the step instead of hanging the run.
on_role() {
  local role="$1" cmd="$2" ssh_args limit="${ON_ROLE_TIMEOUT:-900}"
  ssh_args="$(ssh_of_role "$role")"
  if [[ -z "$ssh_args" ]]; then
    (cd "$_REMOTE_REPO_ROOT" && _with_timeout "$limit" bash -c "$cmd")
  else
    # ServerAlive*: if the path to the machine dies mid-command (e.g. the
    # controller's network changes and the tunnel goes stale), give up after
    # ~30 s instead of waiting on a dead connection forever.
    # shellcheck disable=SC2086  # ssh_args is deliberately word-split
    _with_timeout "$limit" ssh -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=10 \
        -o ServerAliveInterval=10 -o ServerAliveCountMax=3 $ssh_args \
      "cd ~/$REMOTE_DIR 2>/dev/null; $cmd"
  fi
}

# machines — one "role" per distinct machine (the first role naming each host),
# so per-machine measurements are taken once even when roles share a machine.
machines() {
  local seen=" " r h
  for r in $ROLES; do
    h="$(host_of_role "$r")"
    [[ "$seen" == *" $h "* ]] && continue
    seen="$seen$h "
    echo "$r"
  done
}

# roles_on_machine <role> — every role that shares that role's machine
roles_on_machine() {
  local h r out=""
  h="$(host_of_role "$1")"
  for r in $ROLES; do [[ "$(host_of_role "$r")" == "$h" ]] && out="${out:+$out,}$r"; done
  echo "$out"
}
