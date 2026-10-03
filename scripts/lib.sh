# Shared settings for mimir scripts. Source, don't execute.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CACHE="${MIMIR_CACHE:-$ROOT/.cache}"
TOOLS="$CACHE/tools"

VALHEIM_SERVER_APP=896660
BRANCH="${MIMIR_BRANCH:-public}"            # public | public-test
SERVER_DIR="$CACHE/server/$BRANCH"          # vanilla server install, never modified
WORK_DIR="$CACHE/dump/$BRANCH"             # server.log, bepinex.log, raw/
OUT_DIR="$WORK_DIR/raw"                     # raw dump output

DEPOTDOWNLOADER_VERSION=3.4.0
# Iron Gate publishes the public-test password openly in their patch notes.
PUBLIC_TEST_PASSWORD="${MIMIR_PUBLIC_TEST_PASSWORD:-yesimadebackups}"

# The server always runs in an amd64 container. On macOS that needs a full x86_64
# VM (colima + qemu, slow): Rosetta and qemu-user both crash Unity's Mono JIT,
# which relies on MAP_32BIT code allocations they don't honour. A dedicated
# profile keeps the user's default Docker context untouched. Prefer a native
# x86_64 Linux host (scripts/remote.sh) when one is available.
COLIMA_PROFILE="${MIMIR_COLIMA_PROFILE:-mimir-x86}"

log() { printf '\033[1;34m[mimir]\033[0m %s\n' "$*" >&2; }
die() { printf '\033[1;31m[mimir] ERROR:\033[0m %s\n' "$*" >&2; exit 1; }

host_os() { case "$(uname -s)" in Darwin) echo macos ;; Linux) echo linux ;; *) die "unsupported OS $(uname -s)" ;; esac; }
host_arch() { case "$(uname -m)" in arm64|aarch64) echo arm64 ;; x86_64|amd64) echo x64 ;; *) die "unsupported arch $(uname -m)" ;; esac; }

ensure_docker() {
  if [[ "$(host_os)" == macos ]]; then
    command -v colima >/dev/null || die "colima not installed (brew install colima docker)"
    if ! colima status "$COLIMA_PROFILE" >/dev/null 2>&1; then
      log "starting colima profile '$COLIMA_PROFILE' (qemu x86_64; needs: brew install qemu lima-additional-guestagents)"
      colima start "$COLIMA_PROFILE" --vm-type qemu --arch x86_64 \
        --cpu 8 --memory 12 --disk 60 >&2
      # colima switches the global context on start; put the user's back.
      docker context use "${MIMIR_RESTORE_CONTEXT:-desktop-linux}" >/dev/null 2>&1 || true
    fi
    export DOCKER_CONTEXT="colima-$COLIMA_PROFILE"
  fi
  docker info >/dev/null 2>&1 || die "docker daemon not reachable"
}

# Re-run the calling script inside the tools container if any of the given commands is missing
# on this host. The repo is mounted at the same path so every path stays valid.
#   in_tools dotnet unzip   # first line of a script, after sourcing lib.sh
in_tools() {
  local missing=""
  for c in "$@"; do command -v "$c" >/dev/null || missing+=" $c"; done
  [[ -n "${MIMIR_NEED_TOOLS:-}" && -z "${MIMIR_IN_TOOLS:-}" ]] && missing+=" ($MIMIR_NEED_TOOLS)"
  [[ -z "$missing" ]] && return 0
  [[ -n "${MIMIR_IN_TOOLS:-}" ]] && die "missing inside tools container:$missing"
  log "missing:$missing — re-running $(basename "$0") in tools container"
  ensure_docker
  docker build -q -t mimir-tools:latest -f "$ROOT/docker/tools.Dockerfile" "$ROOT/docker" >/dev/null
  mkdir -p "$CACHE/home"
  exec docker run --rm -i --user "$(id -u):$(id -g)" \
    -e MIMIR_IN_TOOLS=1 -e HOME="$CACHE/home" -e MIMIR_BRANCH="$BRANCH" -e MIMIR_CACHE="$CACHE" \
    -e MIMIR_BEPINEX_VERSION="${MIMIR_BEPINEX_VERSION:-}" \
    -v "$ROOT:$ROOT" -w "$ROOT" mimir-tools:latest bash "$ROOT/scripts/$(basename "$0")"
}

# Per-platform python venv with requirements.txt (UnityPy) for the asset extractors; prints its python.
ensure_venv() {
  local venv="$CACHE/venv/$(host_os)-$(host_arch)"
  if ! cmp -s "$ROOT/requirements.txt" "$venv/.requirements"; then
    log "setting up python venv $venv"
    rm -rf "$venv"
    python3 -m venv "$venv"
    "$venv/bin/pip" install -q --disable-pip-version-check -r "$ROOT/requirements.txt" >&2
    cp "$ROOT/requirements.txt" "$venv/.requirements"
  fi
  echo "$venv/bin/python"
}

depotdownloader() {
  local bin="$TOOLS/DepotDownloader-$DEPOTDOWNLOADER_VERSION-$(host_os)-$(host_arch)/DepotDownloader"
  if [[ ! -x "$bin" ]]; then
    local asset="DepotDownloader-$(host_os)-$(host_arch).zip"
    log "fetching $asset"
    mkdir -p "$(dirname "$bin")"
    curl -fsSL -o "$TOOLS/$asset" \
      "https://github.com/SteamRE/DepotDownloader/releases/download/DepotDownloader_$DEPOTDOWNLOADER_VERSION/$asset"
    unzip -qo "$TOOLS/$asset" -d "$(dirname "$bin")"
    chmod +x "$bin"
  fi
  "$bin" "$@"
}
