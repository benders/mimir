#!/usr/bin/env bash
# Run the dedicated server headless with Mimir.Dumper and collect the dump into $OUT_DIR.
# Exits non-zero unless a complete dump (manifest.json + MIMIR_DUMP_OK) was produced.
source "$(dirname "$0")/lib.sh"

TIMEOUT="${MIMIR_DUMP_TIMEOUT:-900}"
IMAGE=mimir-runtime:latest

[[ -f "$SERVER_DIR/valheim_server.x86_64" ]] || "$ROOT/scripts/fetch-server.sh"
PACK="$("$ROOT/scripts/fetch-bepinex.sh")"
DLL="$("$ROOT/scripts/build-plugin.sh")"

ensure_docker
log "building runtime image"
docker build -q --platform linux/amd64 -t "$IMAGE" "$ROOT/docker" >/dev/null

WORK="$WORK_DIR"
rm -rf "$WORK" && mkdir -p "$OUT_DIR"
LOG="$WORK/server.log"

name="mimir-dump-$BRANCH-$$"
log "starting server container $name (timeout ${TIMEOUT}s)"
docker run -d --name "$name" --platform linux/amd64 --user "$(id -u):$(id -g)" \
  -v "$SERVER_DIR:/server:ro" -v "$PACK:/bepinex:ro" -v "$(dirname "$DLL"):/plugin:ro" \
  -v "$WORK:/work" "$IMAGE" >/dev/null
trap 'docker rm -f "$name" >/dev/null 2>&1 || true' EXIT

start=$SECONDS
while [[ "$(docker inspect -f '{{.State.Running}}' "$name")" == true ]]; do
  if (( SECONDS - start > TIMEOUT )); then
    docker logs "$name" >"$LOG" 2>&1 || true
    die "timed out after ${TIMEOUT}s; log: $LOG"
  fi
  sleep 5
done
code="$(docker inspect -f '{{.State.ExitCode}}' "$name")"
docker logs "$name" >"$LOG" 2>&1 || true
log "server exited with code $code after $((SECONDS - start))s; log: $LOG"

grep -q MIMIR_DUMP_OK "$LOG" "$WORK/bepinex.log" 2>/dev/null || die "dump did not report success (see $LOG)"
[[ -f "$OUT_DIR/manifest.json" ]] || die "no manifest.json in $OUT_DIR"
log "dump complete: $(grep -h -o 'MIMIR_DUMP_OK.*' "$LOG" "$WORK/bepinex.log" 2>/dev/null | head -1)"
