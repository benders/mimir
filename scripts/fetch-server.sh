#!/usr/bin/env bash
# Download (or update) the Valheim dedicated server for Linux x64.
# Anonymous Steam login; no game license needed.
source "$(dirname "$0")/lib.sh"
in_tools unzip curl

args=(-app "$VALHEIM_SERVER_APP" -os linux -osarch 64 -dir "$SERVER_DIR")
if [[ "$BRANCH" != public ]]; then
  args+=(-beta "$BRANCH" -betapassword "$PUBLIC_TEST_PASSWORD")
fi

log "downloading server app $VALHEIM_SERVER_APP branch=$BRANCH -> $SERVER_DIR"
mkdir -p "$SERVER_DIR"
depotdownloader "${args[@]}" >&2

[[ -f "$SERVER_DIR/valheim_server.x86_64" ]] || die "server binary missing after download"
chmod +x "$SERVER_DIR/valheim_server.x86_64"
log "server ready ($(du -sh "$SERVER_DIR" | cut -f1))"
