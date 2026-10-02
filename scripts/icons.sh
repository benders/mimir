#!/usr/bin/env bash
# Extract the icons referenced by the raw dump from the server's asset bundles -> $WORK_DIR/icons/.
# Runs anywhere with python3 (no x86_64 needed); UnityPy goes into a per-platform venv.
source "$(dirname "$0")/lib.sh"
# Distro pythons may lack venv/ensurepip (python3-venv); the tools image has it.
python3 -c 'import ensurepip, venv' 2>/dev/null || MIMIR_NEED_TOOLS="python3-venv"
in_tools python3

[[ -f "$OUT_DIR/manifest.json" ]] || die "no raw dump at $OUT_DIR (run dump first)"
[[ -d "$SERVER_DIR/valheim_server_Data" ]] || die "no server at $SERVER_DIR (run fetch-server first)"

VENV="$CACHE/venv/$(host_os)-$(host_arch)"
STAMP="$VENV/.requirements"
if ! cmp -s "$ROOT/requirements.txt" "$STAMP"; then
  log "setting up python venv $VENV"
  rm -rf "$VENV"
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install -q --disable-pip-version-check -r "$ROOT/requirements.txt"
  cp "$ROOT/requirements.txt" "$STAMP"
fi

log "extracting icons"
"$VENV/bin/python" "$ROOT/scripts/extract-icons.py" "$SERVER_DIR" "$OUT_DIR" "$WORK_DIR/icons"
