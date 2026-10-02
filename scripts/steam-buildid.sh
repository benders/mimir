#!/usr/bin/env bash
# Print the current Steam build id of the dedicated server's public branch (e.g. 25527701).
# Beta branches are ignored: mimir only tracks the public release.
# Uses Valve's steamcmd (anonymous app_info_print) in a container; needs real x86_64.
source "$(dirname "$0")/lib.sh"

ensure_docker
docker build -q --platform linux/amd64 -t mimir-steamcmd:latest -f "$ROOT/docker/steamcmd.Dockerfile" "$ROOT/docker" >/dev/null
docker run --rm --platform linux/amd64 mimir-steamcmd:latest \
    +login anonymous +app_info_update 1 +app_info_print "$VALHEIM_SERVER_APP" +quit \
  | python3 "$ROOT/scripts/steam-buildid.py" "$VALHEIM_SERVER_APP"
