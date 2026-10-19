---
title: Multiplayer
summary: Player-count damage scaling, which client runs each creature, and other differences with more players.
sources: Game.GetPlayerDifficulty; Game.GetDifficultyDamageScaleEnemy; Game.GetDifficultyDamageScalePlayer; Player.GetPlayersInRangeXZ; Character.Damage; Character.RPC_Damage; Character.ApplyDamage; SE_Burning.UpdateStatusEffect; SE_Poison.UpdateStatusEffect; Attack.DoMeleeAttack; Projectile.IsValidTarget; BaseAI.UpdateAI; Humanoid.OnAttackTrigger; Game.FixedUpdate; ZDOMan.Update; ZDOMan.AddPeer; ZDOMan.ReleaseZDOS; ZDOMan.ReleaseNearbyZDOS; ZDOMan.IsInPeerActiveArea; ZNetScene.PointInsideActiveArea; ZoneSystem.GetZonePos; ZNet.GetSyncedSimulationDistance; Ship.UpdateOwner; Vagon.RPC_RequestOwn; Sadle.RPC_RequestControl; Container.RPC_RequestOpen; ItemDrop.RPC_RequestOwn; SpawnSystem.UpdateSpawning; SpawnSystem.UpdateSpawnList; SpawnSystem.FindBaseSpawnPoint; SpawnSystem.IsSpawnPointGood; TriggerSpawner.Spawn; RandEventSystem.UpdateRandomEvent; Game.UpdateSleeping; Game.EverybodyIsTryingToSleep; ZNet.GetAllCharacterZDOS
---

Creatures don't get more health with more players. Instead they take less damage and deal a little more. "Creature"
means anything that isn't a player, tames included. The player count is taken at the character being hit, on the
machine of the client that owns the creature: every player within 100 m of it, measured horizontally, up to 5. The
reduction on damage a creature takes comes last, after resistances and armor, and is applied again at each fire, spirit
and poison tick. The bonus on damage a creature deals comes first, before block, resistances and armor, once per hit.
Players can only hurt each other when both have PvP turned on.

- n = players within `m_difficultyScaleRange` (XZ) of the hit character, clamped to [1, `m_difficultyScaleMaxPlayers`]
- damage a creature takes × $1 / (1 + 0.3(n - 1))$ (`m_healthScalePerPlayer`), from any source
- damage a creature deals × $1 + 0.04(n - 1)$ (`m_damageScalePerPlayer`), n counted at its target

{{player-scaling}}

## Boss health, effectively

{{boss-scaling}}

## Ownership

Every saved object in the world (creatures, items on the ground, ships, carts, chests, build pieces) is run by one client,
its owner. The owner runs a creature's AI, attacks and [regeneration](mechanic:healing), and applies the damage it takes:
a player's attack is worked out on the attacker's machine and sent to the owner, which then checks dodge, block,
resistances and health. Others see the result when the owner's update reaches them. Each player always owns their own
character. A dedicated server has no player, so it owns nothing and runs no creatures.

Every 2 s the server goes through the host's own player (if any), then each client in the order they joined, and looks
at the objects near that player: an object it owns that has left its active area is released, and an object with no
owner, or whose owner's active area no longer holds it, is taken over if it lies in this player's active area. So an
owner keeps a creature until it moves away or leaves, then the first player in that order who is close enough takes over.

- active area: Chebyshev distance ≤ 1.5 × 64 m = 96 m from the centre of the player's 64 m zone; the server's Simulation
  distance setting decides it for everyone: 64 m at the lowest, also within a 112 m circle at the next, no larger above
- ship: when its owner isn't aboard, ownership passes to a player who is
- cart, saddle: the player who takes hold of it becomes the owner, unless someone else is using it
- chest: the player who opens it becomes the owner; only one player can have it open at a time
- item on the ground: the player picking it up becomes the owner first

## Spawning, raids and sleep

World spawns run per 64 m zone, on the zone owner's client, only while a player stands in the zone. Each spawn entry
has one timer per zone, and its creature limit counts the 5 × 5 zones centred on it. A group appears 40–80 m (by
default) from a random player in the zone, but never within the minimum distance of any player. So players spread over
several zones get more spawn rolls, though the overlapping limits keep the number of creatures around each one about the
same. Raids start at a random valid player ([raids](mechanic:raids)). Trigger spawners allow `m_maxExtraPerPlayer` × n
more creatures, rounded down; the Seeker spawners in the Queen's citadel allow 2, 3, 4, 4, 5 of each kind within 50 m
for 1–5 players. The night is skipped only when every player is in bed; dead and loading players don't count.

- trigger spawner limit = m_maxSpawned + ⌊m_maxExtraPerPlayer × n⌋ of the picked prefab within m_maxSpawnedRange
