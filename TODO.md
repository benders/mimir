# TODO

Ordered by priority within each section. Check items off in the same commit that completes them.

## Next steps

- [ ] **Static site generator + search.** Read `data/*.json`, copy icons from `.cache/dump/<branch>/icons/`,
      emit static HTML (item, creature, piece, status effect pages; recipe and "used in"/"dropped by" back-links
      derived at build time) plus a client-side search index. Icons ship with the site, never in git.
- [ ] **CI.** GitHub Actions on an x86_64 runner: poll the Steam build id for app 896660 (public and
      public-test), run `make check` when it changes, commit the `data/` diff, build and deploy the site.
      Replaces the `nic@mini` runner for unattended updates.

## Data correctness (found while spot-checking)

- [ ] **Enemy-only item copies.** `FW_*` (Fallen Warrior) and `SP_*` (Shadow Person) items duplicate player
      gear (e.g. three "Black Metal Tower Shield"s). Flag items that have no recipe, no drop/source and are only
      referenced from creature equipment, and hide them on the site.
- [ ] **Creature "attacks" include armor.** `creatures.attacks` unions `m_randomSets` items, which contain
      helmets/armor (`FW_HelmetBronze`). Keep only weapon item types.
- [ ] **Drop amount ranges are off by one.** Unity's `Random.Range(int min, int max)` excludes `max`, so a
      `CharacterDrop` of 1–3 really yields 1–2 (`Game.ScaleDrops`, default resource rate). Emit the effective
      range. Check the same for `DropTable` (`m_stackMin/Max`) before changing it.
- [ ] **Rich-text tags in names** (`<color=orange>Brenna</color>`). Strip for display, keep a `named`/`miniboss` flag.
- [ ] **Shield `armor`.** Shields carry `m_armor` but the game only sums helmet/chest/legs/shoulder armor.
      Omit `armor` for non-armor item types.
- [ ] **Spawner-only creatures.** Creatures placed by `Spawner_*`/`CreatureSpawner` prefabs (e.g. Cultist in
      Frost Caves) and raid events (`RandEventSystem`) don't appear in `spawns.json`. Add those sources.
- [ ] **Projectile / AoE damage.** Some creature attacks deal damage through the spawned projectile or `Aoe`
      prefab rather than the attack item. Resolve the real damage source for attack stats.
- [ ] **Unresolved localization tokens** (32, listed in `data/meta.json`). Decide on fallbacks (prettified
      prefab name) for the site.

## Automated tests

- [ ] **Unit tests for `normalize.py`** (stdlib `unittest`, small fixture dumps under `tests/fixtures/`):
      token resolution, `prune`, damage/modifier maps, drop tables, ref filtering, status-effect default diffing.
- [ ] **Golden-file test**: normalize a checked-in mini fixture and compare with expected output.
- [ ] **Mechanics calculators** (once they exist, see below) tested against values worked out from the
      decompiled code (e.g. block of 70 vs. block power 104 → 11.8 through).
- [ ] **Plugin build check** without game DLLs is impossible; keep `make check` as the integration test and
      add `make test` for everything that runs offline (`unittest` + `verify_data.py` on committed `data/`).
- [ ] Wire `make test` into CI on every push; `make check` only on game updates (it needs the runner).

## Non-item pages (game mechanics)

Write as site pages, citing the game version the behavior was verified against. Source notes from the first
investigation are in [docs/mechanics.md](docs/mechanics.md).

- [ ] **Blocking**: block power formula, damage through, stamina, stagger, durability, parry, skill effect.
      Include an interactive calculator (shield + level + skill vs. attack).
- [ ] **Drops**: pseudo-random drops (≤30% chance), star multipliers, who rolls drops in multiplayer.
- [ ] **Creature levels (stars)**: damage +50%/star, drop multipliers.
- [ ] **Damage types and resistances**: modifier values (Weak, Resistant, ...), armor formula.
- [ ] Later: food/stat stacking, comfort/rested, skills XP, upgrade costs.
