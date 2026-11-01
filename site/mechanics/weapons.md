---
title: Weapons
summary: Every weapon by category, with attack speed and damage per second.
sources: Attack.Start; Projectile.Setup; Projectile.SpawnOnHit; Aoe.Setup; Attack.FireProjectileBurst; Attack.ProjectileAttackTriggered; Attack.UpdateProjectile; Attack.Stop; Player.PlayerAttackInput; Player.UpdateWeaponLoading; Attack.GetAttackEitr; SpawnAbility.Spawn; Character.GetRandomSkillFactor; Tameable.Command; Tameable.UnsummonMaxInstances; SpawnSystem.GetNrOfInstances; Attack.OnAttackTrigger; Player.UpdateAttackBowDraw; Player.UpdateActionQueue; Player.QueueReloadAction; Player.InMinorAction; Humanoid.GetAttackDrawPercentage; ItemData.GetWeaponLoadingTime; Attack.Update; Attack.CanStartChainAttack; Attack.ModifyDamage; Attack.DoMeleeAttack; Attack.DoAreaAttack; Humanoid.StartAttack; Player.InAttack; CharacterAnimEvent.Speed; CharacterAnimEvent.CustomFixedUpdate; Skills.GetRandomSkillFactor; Humanoid.UpdateAttack
---

No item field sets attack speed. The animator does: an attack fires the trigger `m_attackAnimation` + chain level and
lasts while the player's animator state is tagged attack, until the state's exit time. A new attack can't start
before then, except the next chain level, which may start at the clip's Chain event; more than 0.2 s out of an
attack restarts the combo at its first level. Speed events in the clip change
the playback speed part-way through. Each Hit event deals the attack's damage once. A melee hit that connects
freezes the animation for 0.15 s. Skills and status effects don't change attack speed.

- level time = clip time from the start to min(Chain event, exit time), divided by state speed × the current Speed event value
- cycle = Σ level times + 0.15 s × melee hits
- combo damage = hit damage × damage multiplier × hits, with the last level's hits × 2 (melee) or × the area attack's last-chain multiplier
- DPS = combo damage / cycle
- bow: shot time = max(draw, release animation), draw = m_drawDurationMin × (1 − 0.8 × skill / 100)
- crossbow: shot time = fire animation + reload + "reload done" animation (1.15 s), reload = m_reloadTime × (1 − 0.5 × skill / 100)
- each hit rolls × [n − 0.15, n + 0.15], clamped to [0, 1], n = 0.4 + 0.6 × skill / 100 (× 0.85–1 at skill 100)
- held staff (Staff of Frost): shot time = m_burstInterval (0.2 s) after a 0.35 s wind-up, each shot paying the eitr cost; released or out of eitr, it stops
- Dundr: shot time = fire animation + reload, as a crossbow with no "reload done"; reloading drains 25 eitr/s, so a shot costs 25 × reload
- eitr, stamina and health cost = cost × (1 − 0.33 × skill / 100)
- shot damage = weapon damage × projectiles (Dundr 12) × spawned copies that carry it (Staff of Fracturing: 12 splinters)
- summon's hit = its damage × √U(0.75, 1) × (1 + 0.02 × the staff's skill level when summoned): up to ×3 at skill 100
- summons out: no new one while m_maxSpawned of that creature are loaded (anyone's); Dead Raiser and Spirit Caller summons
  follow you, and each new one unsummons your oldest of that creature beyond the staff's quality (1–4)

The tables group weapons by category, with the skill each trains, lowest primary DPS first; a weapon's secondary
attack is in the same row. They use quality 1 (not upgraded; each item page has DPS per quality), a skill roll of 1 (every hit connects at full damage) and the sum of the weapon's damage
types, leaving out any type more than half of all creatures are immune to or ignore: chop and pickaxe, and spirit,
which is marked *. Weapons that fire several projectiles (†) count all of them hitting one target, and Dundr's time is
at skill 0. A staff's projectile may spawn more on hit: copies that carry the weapon's damage count, objects with their
own fixed damage (Lightning Strike's 400 + 80 lightning strike, Echo Spike's blasts) don't; each item page lists them
under Damage dealt. Thrown spears (the spear has to be picked up again) and summoning staffs aren't listed, nor is the
Butcher Knife, which only hits tamed creatures.

> Inferred: times are computed from the animator data, not measured in game; transition blending and input latency
> (about one frame) aren't counted. Bows assume the next draw starts the moment the arrow is released. Burst
> timers count down in fixed-update steps, which may add a step to each 0.2 s shot.

## Melee, staffs and throwables

{{weapons}}

## Bows and crossbows

Speed only: damage per shot is the weapon's plus the ammo's, so DPS depends on the arrows or bolts used. A bow's
damage scales with the draw fraction, so releasing early (once the release animation allows) trades damage for
speed one for one, with slower, less accurate arrows.

{{weapons-ranged}}
