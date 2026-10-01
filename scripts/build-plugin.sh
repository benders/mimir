#!/usr/bin/env bash
# Build the Mimir.Dumper BepInEx plugin against the downloaded server's assemblies.
source "$(dirname "$0")/lib.sh"
in_tools dotnet

MANAGED="$SERVER_DIR/valheim_server_Data/Managed"
[[ -f "$MANAGED/assembly_valheim.dll" ]] || die "no server at $SERVER_DIR — run scripts/fetch-server.sh"
PACK="$("$ROOT/scripts/fetch-bepinex.sh")"

OUT="$CACHE/build/plugin"
log "building plugin -> $OUT"
dotnet build "$ROOT/plugin/Mimir.Dumper/Mimir.Dumper.csproj" -c Release --nologo -v quiet \
  -p:ValheimManaged="$MANAGED" -p:BepInExCore="$PACK/BepInEx/core" -o "$OUT" >&2
[[ -f "$OUT/Mimir.Dumper.dll" ]] || die "build produced no DLL"
echo "$OUT/Mimir.Dumper.dll"
