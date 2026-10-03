---
title: Creature levels (stars)
summary: Star rolls by spawner; health, damage and drop multipliers.
order: 3
sources: SpawnSystem.Spawn; SpawnSystem.GetLevelUpChance; SpawnArea.SpawnOne; SpawnArea.GetLevelUpChance; CreatureSpawner.Spawn; TriggerSpawner.Spawn; BiomeSector.GetLevelUpChanceMultiplier; Character.SetLevel; Character.SetupMaxHealth; Attack.ModifyDamage; Attack.GetLevelDamageFactor; CharacterDrop.GenerateDropList; Procreation.Procreate; Growup.GrowUpdate; EnemyHud.UpdateHuds; LevelEffects.SetupLevelVisualization
---

Stars = level − 1. Spawners start at their minimum level and step up one level per successful roll of the level-up
chance until a roll fails or the maximum is reached. Chance: world spawns 10% (per-entry override), spawn areas 15%,
creature and trigger spawners 10%; locations can override min/max/chance. World modifiers multiply it; at world level
$w > 0$ it becomes $min(70, c^{1.15w})$. Offspring keep the larger of parent level and their minimum; grown-up
creatures keep theirs.

- health $= base × level$
- damage $= × (1 + 0.5 × stars)$
- [level-multiplied drops](mechanic:drops) $= × 2^{stars}$
- $P(m + k) = c^k(1 - c)$, $P(M) = c^{M-m}$

{{chart stars}}

{{star-odds}}

## Always starred

{{guaranteed-stars}}

## Stars by creature

{{star-spawns}}
