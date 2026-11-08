---
title: Player base
summary: Where creatures stop spawning, what counts as a base for raids, and what a Ward protects.
sources: EffectArea.IsPointInsideArea; Fireplace.Start; Fireplace.UpdateState; Piece.IsPlacedByPlayer; EffectArea.GetBaseValue; EffectArea.Awake; SpawnSystem.IsSpawnPointGood; CreatureSpawner.UpdateSpawner; Player.UpdateBaseValue; Player.IsSafeInHome; RandEventSystem.CheckBase; ItemDrop.TimedDestruction; ItemDrop.IsInsideBase; MonsterAI.UpdateAI; ShieldGenerator.UpdateShield; ShieldGenerator.CheckProjectile; CraftingStation.GetExtensions; Player.UpdatePlacementGhost; Player.RemovePiece; Player.Repair; Attack.SpawnOnHitTerrain; PrivateArea.CheckAccess; PrivateArea.IsInside; PrivateArea.HaveLocalAccess; PrivateArea.Interact; PrivateArea.RPC_ToggleEnabled; PrivateArea.RPC_TogglePermitted; PrivateArea.OnObjectDamaged; WearNTear.RPC_Damage
---

Many pieces carry a PlayerBase area: an invisible trigger, a sphere around the piece (a 200 m tall capsule for the
crafting stations, so only the horizontal distance matters). No world spawn picks a point inside one, and no
location spawner inside one spawns; only the Ashlands cinder rain spawns ignore it, and spawner objects such as
Greydwarf nests never check it. Dropped items inside one (above 28 m altitude) never despawn. Torches, fires and braziers have theirs only when a player built them, lit or not, even with no fuel; the camp fires that come with the world (Fuling villages, the traders') have none. A Resin Candle's sits in its fuel states, so it counts only while it has fuel. The area is
not what the piece shows: a Workbench's build circle and its base area are both 20 m, but the Wisp Torch clears mist
to 24 m, a Ward guards 32 m and the Shield Generator's dome reaches 30 m, beyond their 20 m base areas.

Every 2 s each player counts the PlayerBase areas that touch a 20 m sphere around them; raids that need a base start
only at players with a count of 3 or more. A piece therefore counts from up to 20 m plus its own radius away.

- spawn blocked at point $p$ when $p$ is inside any PlayerBase collider
- base value = number of base pieces with $d < 20 + r$ ($d$: distance from the player, $r$: the piece's radius; for spheres)
- raid with "near base": base value ≥ 3; safe at home (music, time-in-base stat): resting in shelter with base value ≥ 1

> Inferred: the Eternal Pyre's PlayerBase object has scale 0 and the Dvergr ward's is disabled in the prefab, so
> neither counts; the Shield Generator's second, disabled 30 m capsule never switches on.

## The Ward

A Ward (PrivateArea) is a separate area: 32 m measured horizontally, at any height. Its builder turns it on and off;
while it is off anyone can add or remove themselves as permitted. While it is on, a player who is neither the builder
nor permitted can't place, remove or repair pieces, dig or flatten terrain, or open doors, chests, portals and other
devices inside it; where several Wards overlap, access to any one of them is enough. A new Ward can't be placed so
that its circle overlaps an active Ward the player has no access to. Damage to a piece inside an active Ward flashes
it; a Dvergr ward also turns the Dvergr within 64 m against the attacker (see
[creature behavior](mechanic:creature-behavior)). Its own PlayerBase area is the usual 20 m sphere.

## Shield Generator

While fuelled, the dome stops projectiles fired from outside it; its radius is
$r_{min} + fuel × (r_{max} - r_{min})$ (fuel as a fraction of the maximum), a fixed 30 m. Inside it sits a NoMonsters area: untamed
creatures won't chase a target inside one, and flee from within 7.5 m of it.

> Inferred: the NoMonsters area scales with the dome, but its bounds are taken once when it first switches on, so it
> may be smaller than the dome.

## Radii

{{player-base-radii}}
