# mimir — agent guide

Companion website for Valheim. Game data is extracted automatically from the **dedicated server**
(Steam app 896660, anonymous download, no game license) by running it headless with a BepInEx
plugin that dumps everything to JSON.

## Pipeline

```
fetch-server.sh  DepotDownloader -> .cache/server/<branch>/          (2 GB, cached)
fetch-bepinex.sh Thunderstore BepInExPack_Valheim (pinned) -> .cache/tools/
build-plugin.sh  plugin/Mimir.Dumper -> .cache/build/plugin/Mimir.Dumper.dll
dump.sh          server + BepInEx in Docker (amd64) -> .cache/dump/<branch>/raw/
verify.py        invariant checks on the raw dump
remote.sh        runs any of the above on a native x86_64 Linux host, pulls the dump back
```

## Commands (all non-interactive; non-zero exit = failure)

- `make check` — **the end-to-end test**: dump on `$(REMOTE)` (default `nic@mini`), then verify. ~2 min warm.
- `make remote-dump` / `make verify` — the two halves.
- `make dump` — run locally. Only practical on x86_64 Linux; on macOS it uses a qemu x86_64 VM and is very slow.
- `make decompile` — decompile game assemblies into `.cache/decompiled/` for reference.
- `BRANCH=public-test make check` — same for the public test branch.

Logs after a dump: `.cache/dump/<branch>/server.log` (Unity) and `bepinex.log` (plugin; look for `MIMIR_DUMP_OK` / `MIMIR_DUMP_FAILED`).

## Hard constraints

- **Never commit game files** (DLLs, assets, decompiled source). `.cache/` is gitignored for this reason.
- The server must run on **real x86_64**. Rosetta and qemu-user both crash Unity's Mono JIT
  (`x86-codegen.h:410 offset == (gint32)offset`; it needs MAP_32BIT allocations). Don't retry them.
- Remote host needs only Docker + key-based SSH. Missing tools (dotnet, unzip) are handled by
  re-running the script in `docker/tools.Dockerfile` (`in_tools` in `scripts/lib.sh`).
- The plugin is read-only: no Harmony patches. It serializes fields by Unity's own rules (public or
  `[SerializeField]`), so new game fields appear without code changes. References to other objects
  are written as `{"$ref": "<prefab>"}`, sprites as `{"$sprite": "<name>"}`.
- `verify.py` checks invariants (counts, known vanilla content), not exact values, so balance
  patches don't break it. Add a check whenever a new data area is relied upon.

## Raw dump layout (`.cache/dump/<branch>/raw/`)

- `manifest.json` — game version, counts, warnings, icon probe. Written last = dump complete.
- `prefabs/<name>.json` — each prefab's game components (`ItemDrop`, `Humanoid`, `CharacterDrop`, `Piece`, ...).
- `recipes.json`, `status_effects.json` — ObjectDB ScriptableObjects.
- `world/*.json` — ZoneSystem (vegetation, locations), EnvMan (biomes, weather), SpawnSystemList, RandEventSystem.
- `localization/English.json` — `$token` → text (keys without the `$`).

## Status / next steps

1. Icons: the server includes the icon atlas (BC7, not readable at runtime). Plan: the plugin writes sprite
   rects; extract the atlas offline (UnityPy) and crop.
2. Normalize raw dump → compact site data (`data/`, committed, diffable per game version).
3. Static site generator + search.
4. CI: GitHub Actions (x86_64) on Steam build-id change.
