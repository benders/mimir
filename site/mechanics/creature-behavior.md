---
title: Creature behavior
summary: How creatures pick fights; neutral Dvergr and what makes them hostile.
sources: BaseAI.IsEnemy; BaseAI.IsAggravated; BaseAI.SetAggravated; BaseAI.RPC_SetAggravated; BaseAI.AggravateAllInArea; Character.RPC_Damage; MonsterAI.UpdateTarget; MonsterAI.OnPrivateAreaAttacked; NpcTalk.OnPrivateAreaAttacked; PrivateArea.OnObjectDamaged; PrivateArea.CheckAccess; WearNTear.RPC_Damage; Destructible.RPC_Damage; MineRock5.RPC_Damage; Container.Interact; Pickable.RPC_Pick; SpawnAbility.Spawn; Attack.DoMeleeAttack; Attack.DoAreaAttack; Projectile.IsValidTarget; Aoe.ShouldHit
---

## Neutral creatures

Dvergr leave players and tame creatures alone: the faction table makes the Dverger and Players factions non-hostile
both ways, while Dvergr and the other monsters (Seekers, Gjall) still fight each other. Each creature below also
carries an aggravated flag, saved with that creature and never cleared. Once it is set, that one creature is hostile
to players and tames, and may go after player buildings. Hostility spreads by distance, not by faction: Dvergr in
other camps, and ones that spawn later, stay neutral.

- hitting one for more than 0 damage aggravates every such creature within 20 m of it, and alerts them
- damaging a building piece, destructible or rock inside a Dvergr guard stone's 32 m area: each Dverger-faction
  creature within 64 m counts the hit and turns after more than its threshold below (5 for Dvergr), or at once if
  the object breaks; they shout a warning first. The count is kept only in memory, so reloading resets it
- a creature summoned by an aggravated Dvergr mage starts aggravated
- your attacks still hit them: melee, projectiles and area effects treat an aggravatable creature as a target, so a
  stray area hit counts
- some chests in Dvergr camps are locked while the guard stone stands (Container m_checkGuardStone); breaking the stone
  opens them and aggravates everyone within 64 m. Opening the unlocked chests doesn't anger anyone

{{neutral-creatures}}

The Seal is aggravatable too, but its faction is hostile to players anyway; hitting one only spreads the flag to any
Dvergr within 20 m.

> Inferred: the game also has a theft trigger (a Pickable with m_aggravateRange aggravates everyone within that range
> when picked), but its only user, Pickable_DvergerThing, isn't placed in the world.
