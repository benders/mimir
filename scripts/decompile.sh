#!/usr/bin/env bash
# Decompile the game assemblies -> .cache/decompiled/<assembly>/ (reference only, never commit). ilspycmd is pinned
# in dotnet-tools.json and needs the .NET 10 SDK; hosts without one run this in the tools container.
source "$(dirname "$0")/lib.sh"
command -v dotnet >/dev/null && ! dotnet --list-sdks 2>/dev/null | /usr/bin/grep -q -e '^10\.' && export MIMIR_NEED_TOOLS="dotnet 10 SDK"
in_tools dotnet

MANAGED="$SERVER_DIR/valheim_server_Data/Managed"
[[ -f "$MANAGED/assembly_valheim.dll" ]] || die "no server at $SERVER_DIR — run scripts/fetch-server.sh"
cd "$ROOT"
dotnet tool restore >&2
for a in assembly_valheim assembly_utils assembly_guiutils SoftReferenceableAssets; do
  rm -rf "$CACHE/decompiled/$a"  # a type removed from the game must not linger
  log "decompiling $a"
  dotnet ilspycmd -p -o "$CACHE/decompiled/$a" "$MANAGED/$a.dll" >/dev/null
done
