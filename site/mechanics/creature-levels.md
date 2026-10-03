---
title: Creature levels (stars)
summary: How a creature gets its stars, and what stars do to health, damage and drops.
order: 3
sources: SpawnSystem.Spawn; SpawnSystem.GetLevelUpChance; SpawnArea.SpawnOne; SpawnArea.GetLevelUpChance; CreatureSpawner.Spawn; TriggerSpawner.Spawn; BiomeSector.GetLevelUpChanceMultiplier; Character.SetLevel; Character.SetupMaxHealth; Attack.ModifyDamage; Attack.GetLevelDamageFactor; CharacterDrop.GenerateDropList; Procreation.Procreate; Growup.GrowUpdate; EnemyHud.UpdateHuds; LevelEffects.SetupLevelVisualization
---

## Levels and stars

Every creature has a *level*, which starts at 1. The stars in the game are the levels above the first: **stars = level - 1**,
so an unstarred creature is level 1 and a one-star creature is level 2 (`Character.SetLevel`, `Character.GetLevel`).
The spawn data on this site holds levels; the creature pages show them as stars.

The health bar of a creature has star icons that are switched on for level 2 and level 3 only
(`EnemyHud.UpdateHuds`: `level == 2`, `level == 3`); the code switches on nothing for higher levels. A starred creature
also gets its own size and color from the creature's `LevelEffects` setup (`SetupLevelVisualization`).

## What stars do

| | Formula | Source |
|---|---|---|
| Maximum health | base health × level | `Character.SetupMaxHealth` |
| Damage of its attacks | × (1 + 0.5 × (level - 1)) | `Attack.GetLevelDamageFactor`, applied in `Attack.ModifyDamage` |
| Level-multiplied drops | chance and amount × 2^(level - 1) | `CharacterDrop.GenerateDropList` |

So one star doubles the health, adds half to the damage and doubles the level-multiplied drops, and every further star
adds another full health value, another half of the damage and doubles the drops again.

{{chart stars}}

`Attack.ModifyDamage` is called for the creature's melee attacks, area attacks and projectile bursts (`DoMeleeAttack`,
`DoAreaAttack`, `FireProjectileBurst`). Damage that comes from some other component, such as a spawned area
effect with its own damage, was not checked. Armor, resistances and blocking then work on the scaled damage
([Damage types](mechanic:damage-types), [Blocking](mechanic:blocking)). Only drops with the *level multiplier* flag scale; see
[Drops](mechanic:drops).

A creature that grows up (`Growup`) keeps its level, and one born from `Procreation` gets the larger of its parent's level and
the minimum offspring level.

## How a creature gets stars

Spawners decide the level when they create the creature. There are four kinds (`SpawnSystem`, `SpawnArea`,
`CreatureSpawner` and `TriggerSpawner`) and they all roll the same way:

1. Start at the spawner's minimum level.
2. While below the maximum level: with the level-up chance, go up one level and roll again; otherwise stop.
3. If the result is above level 1, the creature is set to that level.

The chance is a percentage between 0 and 100 (`Random.Range(0f, 100f) <= chance`). With chance $c$ and a range of levels
from $m$ to $M$, the odds of stopping at level $m + k$ are $c^k (1 - c)$, and $c^{(M - m)}$ for the maximum level.

{{star-odds}}

What the chance is depends on the spawner:

- **World spawns** (`SpawnSystem`): 10% unless the spawn entry sets its own (`m_overrideLevelupChance`); a spawn entry
  can also set a minimum distance from the world center within which nothing is starred (`m_levelUpMinCenterDistance`).
  Neither is in `data/` yet.
- **Spawn areas** (`SpawnArea`): the field `m_levelupChance`, 15 by default.
- **Creature spawners** (`CreatureSpawner`) and **trigger spawners**: the field `m_levelupChance`, 10 by default. A location can
  override the minimum level, maximum level and chance for the spawners inside it
  (`m_enemyMinLevelOverride`, `m_enemyMaxLevelOverride`, `m_enemyLevelUpOverride`).

For world spawns, spawn areas and creature spawners the chance is then changed by the world: the world modifier for the
level-up rate (`Game.m_enemyLevelUpRate`) multiplies it, and so does a per-area multiplier from biome sectors
(`BiomeSector.GetLevelUpChanceMultiplier`). When the world level setting is above 0 the chance becomes
`min(70, chance ^ (world level × 1.15))` instead of `chance × rate` (`SpawnSystem.GetLevelUpChance`, `SpawnArea.GetLevelUpChance`).
Trigger spawners use their chance as is. The numbers on this page are for world level 0 and a rate of 1.

A minimum level above 1 means the creature is always starred. These spawn entries have one:

{{guaranteed-stars}}

## Stars by creature

The highest star count each creature can spawn with, from the spawn entries in `data/` (world spawns, locations, dungeons
and raids; summons and offspring are not counted):

{{star-spawns}}
