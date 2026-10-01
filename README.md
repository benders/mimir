# mimir

A companion website for [Valheim](https://www.valheimgame.com/): item and creature stats, recipes,
drops, and more. Data is extracted automatically from the game's dedicated server, so the site
follows game updates without manual editing.

```sh
make check              # dump game data on the x86_64 runner (REMOTE=user@host) and verify it
make help               # all targets
```

See [AGENTS.md](AGENTS.md) for how the pipeline works.

Valheim is a trademark of Iron Gate AB. This is an unofficial fan project, not affiliated with or
endorsed by Iron Gate AB or Coffee Stain. No game files are distributed in this repository.
