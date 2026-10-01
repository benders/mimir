# Runs inside the container.
#   /server   vanilla server install (read-only)
#   /bepinex  BepInExPack_Valheim contents (read-only)
#   /plugin   Mimir.Dumper.dll (read-only)
#   /work     output: raw/ (the dump) and bepinex.log
set -euo pipefail

# Assemble a writable game dir without copying 2 GB: symlink the server files, but copy the
# executable itself so Unity and BepInEx treat $GAME (not /server) as the game root.
GAME=/tmp/game
mkdir -p "$GAME" && cd "$GAME"
for f in /server/*; do ln -s "$f" "$(basename "$f")"; done
rm valheim_server.x86_64 && cp /server/valheim_server.x86_64 . && chmod +x valheim_server.x86_64
cp -r /bepinex/. "$GAME"/
mkdir -p BepInEx/plugins && cp /plugin/Mimir.Dumper.dll BepInEx/plugins/

export DOORSTOP_ENABLED=1
export DOORSTOP_TARGET_ASSEMBLY=./BepInEx/core/BepInEx.Preloader.dll
export LD_LIBRARY_PATH="./doorstop_libs:./linux64:${LD_LIBRARY_PATH:-}"
export LD_PRELOAD="libdoorstop_x64.so"
export SteamAppId=892970
export HOME=/tmp
export MIMIR_OUT=/work/raw
export MIMIR_EXIT=1

status=0
./valheim_server.x86_64 -batchmode -nographics \
  -name mimir -world mimir -password mimir-dump-only -public 0 -port 2456 \
  -savedir /tmp/valheim-save || status=$?

cp BepInEx/LogOutput.log /work/bepinex.log 2>/dev/null || true
exit "$status"
