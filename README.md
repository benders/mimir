# mimir

A companion website for [Valheim](https://www.valheimgame.com/): item and creature stats, recipes, drops,
building pieces, and how the game's mechanics actually work. The data comes straight from the game's
dedicated server, so the site follows game updates without anyone editing pages by hand.

**Status:** data extraction works end to end, and the site itself is next. See [TODO.md](TODO.md).

## What's here

| Path | What |
|---|---|
| `data/` | The extracted game data as compact JSON (items, recipes, creatures, spawns, pieces, ...). Browse it or diff it between game versions. |
| `plugin/` | A small BepInEx plugin that dumps game data from inside a running server. |
| `scripts/` | The pipeline: download, run, extract icons, normalize, verify. |
| `docs/mechanics.md` | Notes on game mechanics (blocking, drop rates, ...) taken from the game code. |
| [Architecture.md](Architecture.md) | How it all fits together, with diagrams. |

## Running it

You need Docker and an x86_64 Linux machine for the extraction step. The game server doesn't run under
emulation on Apple Silicon. A Mac can drive the run on a Linux box over SSH:

```sh
make check REMOTE=user@linux-box   # download server, dump, extract icons, normalize into data/, verify
make help                          # all targets
```

The first run downloads about 2 GB. Later runs take about 3 minutes. If `data/` changed, commit it.

## Legal

Valheim is a trademark of Iron Gate AB. This is an unofficial fan project, not affiliated with or endorsed
by Iron Gate AB or Coffee Stain. No game files (binaries, assets or icons) are stored in this repository.
The server is downloaded from Steam by whoever runs the pipeline.
