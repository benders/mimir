#!/usr/bin/env bash
# Download BepInExPack_Valheim (Thunderstore) — the standard mod loader pack,
# preconfigured for Valheim's Unity/Mono version. Pinned for reproducibility;
# set MIMIR_BEPINEX_VERSION=latest to resolve the newest.
source "$(dirname "$0")/lib.sh"
in_tools unzip curl python3

VERSION="${MIMIR_BEPINEX_VERSION:-5.4.2351}"
PKG_API="https://thunderstore.io/api/experimental/package/denikson/BepInExPack_Valheim"

if [[ "$VERSION" == latest ]]; then
  VERSION="$(curl -fsSL "$PKG_API/" | python3 -c 'import json,sys; print(json.load(sys.stdin)["latest"]["version_number"])')"
fi

DEST="$TOOLS/BepInExPack_Valheim-$VERSION"
if [[ -d "$DEST/BepInExPack_Valheim/BepInEx/core" ]]; then
  log "BepInExPack_Valheim $VERSION already present"
  echo "$DEST/BepInExPack_Valheim"
  exit 0
fi

log "fetching BepInExPack_Valheim $VERSION"
mkdir -p "$DEST"
curl -fsSL -o "$DEST.zip" "https://thunderstore.io/package/download/denikson/BepInExPack_Valheim/$VERSION/"
unzip -qo "$DEST.zip" -d "$DEST"
[[ -d "$DEST/BepInExPack_Valheim/BepInEx/core" ]] || die "unexpected BepInEx pack layout"
echo "$DEST/BepInExPack_Valheim"
