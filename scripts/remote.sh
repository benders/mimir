#!/usr/bin/env bash
# Run a pipeline script on a native x86_64 Linux host (only Docker required there) and pull the
# dump back. The remote keeps its own .cache, so the 2 GB server download is reused.
#
#   MIMIR_REMOTE=user@host scripts/remote.sh dump      # runs scripts/dump.sh remotely
#
# Needs key-based SSH (BatchMode: never prompts).
source "$(dirname "$0")/lib.sh"

REMOTE="${MIMIR_REMOTE:?set MIMIR_REMOTE=user@host}"
REMOTE_DIR="${MIMIR_REMOTE_DIR:-mimir}"   # relative to the remote home
STEP="${1:?usage: remote.sh <script name without .sh> (e.g. dump)}"
[[ -f "$ROOT/scripts/$STEP.sh" ]] || die "no such script: scripts/$STEP.sh"

# One shared connection for every ssh/rsync below: a single key-agent approval per run.
SSH=(ssh -o BatchMode=yes -o ConnectTimeout=10
  -o ControlMaster=auto -o "ControlPath=/tmp/mimir-ssh-%C" -o ControlPersist=120)

log "syncing repo -> $REMOTE:$REMOTE_DIR"
rsync -a --delete -e "${SSH[*]}" \
  --exclude .cache/ --exclude .git/ --exclude node_modules/ --exclude 'bin/' --exclude 'obj/' \
  "$ROOT/" "$REMOTE:$REMOTE_DIR/"

log "running scripts/$STEP.sh on $REMOTE (branch=$BRANCH)"
status=0
"${SSH[@]}" "$REMOTE" "cd $REMOTE_DIR && MIMIR_BRANCH=$BRANCH MIMIR_DUMP_TIMEOUT=${MIMIR_DUMP_TIMEOUT:-900} bash scripts/$STEP.sh" || status=$?

# Pull results back even on failure, so logs are available locally for diagnosis.
if "${SSH[@]}" "$REMOTE" "test -d $REMOTE_DIR/.cache/dump/$BRANCH"; then
  mkdir -p "$WORK_DIR"
  rsync -a --delete -e "${SSH[*]}" "$REMOTE:$REMOTE_DIR/.cache/dump/$BRANCH/" "$WORK_DIR/"
  log "pulled results -> $WORK_DIR"
fi
exit "$status"
