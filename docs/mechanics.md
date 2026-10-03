# Game mechanics notes

Findings from reading the decompiled game code (`make decompile`, Valheim 1.0.16). Source material for the
site's mechanics pages. Re-check against the decompiled code after major game updates.

## Blocking (`Humanoid.BlockAttack`, `HitData`, `ItemDrop.ItemData.GetBlockPower`)

- Block power `B = (block + blockPerLevel × (quality − 1)) × (1 + 0.5 × skill/100)`. Skill is the floored
  Blocking level (status effects can modify it; none do for Blocking in vanilla), clamped to 0–100.
- Parry (`timedBlockBonus > 1`, within 0.25 s of raising the shield): `B ×= timedBlockBonus`. Tower shields
  have no bonus and can't parry.
- The shield's own damage modifiers apply to the hit first (Serpent Scale: pierce Resistant = ×0.5).
- Blockable damage `D` = blunt + slash + pierce + fire + frost + lightning + poison + spirit (+ nonPlayer).
- Damage that gets through uses the armor formula: `D²/(4B)` if `D ≤ 2B`, else `D − B`. Never zero.
- Stamina: `10 × clamp01((D − through)/B)`; a perfect parry costs the player's `m_perfectBlockStaminaDrain` (0).
- The damage that gets through adds to stagger; the player is staggered (guard broken, full hit taken) at
  `maxHP × 0.4`. Running out of stamina also fails the block.
- Durability loss per block: `useDurabilityDrain × D/B`.
- Parry force (knockback) depends only on shield level, not skill. Blocking XP: +1 per block, +2 per parry.

## Creature drops (`CharacterDrop.GenerateDropList`)

- Level multiplier `m = 2^(level − 1)` (1★ = level 2). `levelMultiplier` drops scale both chance and amount by m.
- Amount uses `Random.Range(min, max)` (int, max exclusive) at default resource rate.
- **Pseudo-random drops**: if effective chance `p ≤ 0.3` and the `NoPseudoDrops` global key is unset, a
  per-item countdown replaces the roll. First countdown is uniform in [0, 2/p − 1], after a drop it's uniform
  in [0, 2/p]; it decrements per kill and drops at ≤ 0. Same long-run rate, but at most 2/p kills between
  drops. The counter is a static dictionary keyed by item name and resets if the chance changes.
- Drops are rolled by the **owner** of the creature's ZDO (`CheckDeath` runs only when `IsOwner()`; damage
  RPCs are forwarded to the owner). On a dedicated server the server never owns creatures near players (its
  reference position is parked off-map in `Game.FixedUpdate`), so a **client** rolls the drop, and the
  counters are per client process (reset on relog).

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

## Damage modifiers

- `Ignore` means the damage type does nothing: `HitData.ApplyModifier` returns 0, and a later modifier can't override
  it (`DamageModifiers.ShouldOverride`). Almost every creature ignores `chop` and `pickaxe`; Jotun warriors ignore
  `spirit`, ShadowPerson everything (#27).

## Creature attacks

- Damage scales by level: `1 + 0.5 × (level − 1)` (`Attack.cs`).

## Item quality and upgrade costs (`ItemDrop.ItemData`, `Piece.Requirement.GetAmount`, `Recipe`)

- Damage, armor, durability, block power: `base + (quality − 1) × perLevel` (`GetDamage`, `GetArmor`,
  `GetMaxDurability`, `GetBaseBlockPower`; world level adds more on top).
- Resource cost for quality `q`: `q = 1` → `m_amount`; `q = 2, 3` → `(q − 1) × perLevel`; `q ≥ 4` →
  `(4 + (q − 4) / 2) × perLevel`, floored. So quality 4 costs 4 × perLevel, not 3×.
- Required station level: `max(1, m_minStationLevel) + q − 1` (`GetRequiredStationLevel`).
- `m_upgraderResource` requirements (battle idols) only count at a station with `m_upgrader` (the
  `UpgradeStation` prefab), which can also upgrade past `m_maxQuality` (`InventoryGui`). Not verified in-game.

## Hildir's quests (`Trader.m_useItems`, `CharacterDrop`, `Door.m_keyItem`)

Each of Hildir's minibosses drops her chest directly through `CharacterDrop` (`Skeleton_Hildir` → `chest_hildir1`, and
likewise for the other two). Giving the chest to Hildir (`Trader.m_useItems`: `m_removesItem`, `m_setsGlobalKey`
`Hildir1`–`3`) unlocks more of her stock, whose `requiredKey` is that global key. No key is involved.

The `HildirKey_*` items (Brass, Silver, Bronze Key) look like cut content: their only source is
`TreasureChest_{forestcrypt,mountaincave,plainsfortress}_hildir`, which no location or dungeon room places, and no
`Door.m_keyItem` in the dump or code path refers to them (nothing in the decompiled assembly names them). Verified
against the dump and code, not in-game.
