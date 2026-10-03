#!/usr/bin/env bash
# Extract the player's attack animation timing from the server's asset bundles -> $OUT_DIR/anims/.
# Runs anywhere with python3 (no x86_64 needed); UnityPy goes into a per-platform venv.
source "$(dirname "$0")/lib.sh"
# Distro pythons may lack venv/ensurepip (python3-venv); the tools image has it.
python3 -c 'import ensurepip, venv' 2>/dev/null || MIMIR_NEED_TOOLS="python3-venv"
in_tools python3

[[ -f "$OUT_DIR/manifest.json" ]] || die "no raw dump at $OUT_DIR (run dump first)"
[[ -d "$SERVER_DIR/valheim_server_Data" ]] || die "no server at $SERVER_DIR (run fetch-server first)"

log "extracting attack animations"
"$(ensure_venv)" "$ROOT/scripts/extract-anims.py" "$SERVER_DIR" "$OUT_DIR"
