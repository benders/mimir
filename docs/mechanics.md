# Game mechanics notes

Findings from reading the decompiled game code (`make decompile`, Valheim 1.0.16). Re-check against the decompiled
code after major game updates.

**Where things live.** The site's Mechanics section (`site/mechanics/*.md`, built by `scripts/build-site.py`) is the
source of truth for the topics it covers: blocking, drops, creature levels, damage types and armor, item upgrades.
Those pages state every formula with its decompiled method and the game version, and replace the notes that used to be
in this file (a few of those notes were wrong or incomplete: the Player prefab's block stamina drain is 10 although
the field default is 25, shields without a parry bonus above 1 are not only the tower shields, and creature health
scales with level). This file keeps only what has no page yet. When a topic gets a page, move its notes there and
delete them here.

## Where creatures spawn

- World spawns: `SpawnSystem` lists per biome; some entries place a `CreatureSpawner` prefab instead of the creature.
  Biome masks are `Heightmap.Biome` flags (`-1` = all).
- Raids: `RandEventSystem` events; the event's `m_biome` decides where it can start, its spawners use all biomes.
- Locations: `ZoneSystem.m_locations` are soft-referenced prefabs (`SoftReference<GameObject>`, loaded on demand)
  whose children hold `CreatureSpawner`, `SpawnArea` and boss altars (`OfferingBowl.m_bossPrefab`, summoned with
  `m_bossItems` × `m_bossItem`).
- Dungeons: a location's `DungeonGenerator` uses the enabled rooms from `DungeonDB` whose `Room.Theme` overlaps its
  `m_themes` (`(room.m_theme & m_themes) != 0 && room.m_enabled`, `DungeonGenerator.cs`).
- Offspring: `Procreation.m_offspring` (Hen lays `ChickenEgg`), eggs hatch via `EggGrow.m_grownPrefab`.
- Some creature prefabs (Hen, Leech_cave, Troll_sleeping, Deer_White, ...) aren't referenced by any of these; they
  look unused in vanilla worldgen (inferred from the dump, not verified in-game).

## Hildir's quests (`Trader.m_useItems`, `CharacterDrop`, `Door.m_keyItem`)

Each of Hildir's minibosses drops her chest directly through `CharacterDrop` (`Skeleton_Hildir` → `chest_hildir1`, and
likewise for the other two). Giving the chest to Hildir (`Trader.m_useItems`: `m_removesItem`, `m_setsGlobalKey`
`Hildir1`–`3`) unlocks more of her stock, whose `requiredKey` is that global key. No key is involved.

The `HildirKey_*` items (Brass, Silver, Bronze Key) look like cut content: their only source is
`TreasureChest_{forestcrypt,mountaincave,plainsfortress}_hildir`, which no location or dungeon room places, and no
`Door.m_keyItem` in the dump or code path refers to them (nothing in the decompiled assembly names them). Verified
against the dump and code, not in-game.
