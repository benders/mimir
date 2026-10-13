#!/usr/bin/env bash
# Render every dumped location (and camp room) from the server's asset bundles -> $WORK_DIR/renders/ (#52, #53).
# Runs anywhere with python3 (no x86_64 needed); UnityPy, numpy and numba go into a per-platform venv.
# MIMIR_RENDER_THREADS overrides the thread count (default 8; CI uses its 4 cores).
source "$(dirname "$0")/lib.sh"
# Distro pythons may lack venv/ensurepip (python3-venv); the tools image has it.
python3 -c 'import ensurepip, venv' 2>/dev/null || MIMIR_NEED_TOOLS="python3-venv"
in_tools python3

[[ -f "$OUT_DIR/manifest.json" ]] || die "no raw dump at $OUT_DIR (run dump first)"
[[ -d "$SERVER_DIR/valheim_server_Data" ]] || die "no server at $SERVER_DIR (run fetch-server first)"

log "rendering locations"
"$(ensure_venv)" "$ROOT/scripts/extract-renders.py" "$SERVER_DIR" "$OUT_DIR" "$WORK_DIR/renders" \
  --unpacked "$CACHE/unpacked/$BRANCH" ${MIMIR_RENDER_THREADS:+--threads "$MIMIR_RENDER_THREADS"} "$@"
