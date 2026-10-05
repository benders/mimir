---
title: Raids
summary: When each raid can start, and what it sends.
order: 11
sources: RandEventSystem.UpdateRandomEvent; RandEventSystem.StartRandomEvent; RandEventSystem.GetPossibleRandomEvents; RandEventSystem.GetValidEventPoints; RandEventSystem.InValidBiome; RandEventSystem.CheckBase; RandEventSystem.HaveGlobalKeys; RandEventSystem.PlayerIsReadyForEvent; RandomEvent.Update; Player.UpdateEvents; Player.SetGuardianPower; Character.OnDeath; EffectArea.GetBaseValue; ZoneSystem.GetGlobalKey; SpawnSystem.UpdateSpawning
---

The server rolls for a raid on a timer. On a hit it collects every enabled random event whose world keys are met
and that has at least one valid player, then starts one of them at random, centred on a random valid player. A player
is valid when standing in one of the event's biomes, below 3000 m (not in a dungeon) and, for raids that need a base,
within 20 m of at least 3 base pieces. A raid ends after its duration; its clock stops while no player is within its
range. With the world modifier for player-based raids, the world keys are ignored for raids that list player conditions: each player
qualifies on their own Forsaken power choices, the creatures killed near them and the items they have discovered.

- roll every m_eventIntervalMin × eventRate minutes, starting a raid with m_eventChance / eventRate %
- base = number of PlayerBase effect areas within 20 m of the player; a raid that needs a base needs base ≥ 3
- world keys: every required key set and none of the "until" keys; keys are compared ignoring case
- player-based: none of the "not for" conditions, then any "only for" condition, or no "only for" list at all

{{raid-timing}}

> Inferred: the raid's spawners run alongside the biome's own, for players inside its range (SpawnSystem takes them
> from the active event, which a player only has while in range).

> Inferred: with player-based raids on, the raids whose condition is a text token such as `$se_moder_name` can't
> start, since no code gives a player that key.

## Base pieces

{{raid-base-pieces}}

## Raids

{{raids}}
