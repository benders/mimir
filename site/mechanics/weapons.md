---
title: Weapons
summary: Every weapon by category, with attack speed and damage per second.
order: 7
sources: Attack.Start; Projectile.Setup; Attack.FireProjectileBurst; Attack.OnAttackTrigger; Player.UpdateAttackBowDraw; Player.UpdateActionQueue; Player.QueueReloadAction; Player.InMinorAction; Humanoid.GetAttackDrawPercentage; ItemData.GetWeaponLoadingTime; Attack.Update; Attack.CanStartChainAttack; Attack.ModifyDamage; Attack.DoMeleeAttack; Attack.DoAreaAttack; Humanoid.StartAttack; Player.InAttack; CharacterAnimEvent.Speed; CharacterAnimEvent.CustomFixedUpdate; Skills.GetRandomSkillFactor
---

No item field sets attack speed. The animator does: an attack fires the trigger `m_attackAnimation` + chain level and
lasts while the player's animator state is tagged attack, until the state's exit time. A new attack can't start
before then, except the next chain level, which may start at the clip's Chain event. Speed events in the clip change
the playback speed part-way through. Each Hit event deals the attack's damage once. A melee hit that connects
freezes the animation for 0.15 s. Skills and status effects don't change attack speed.

- level time = clip time from the start to min(Chain event, exit time), divided by state speed × the current Speed event value
- cycle = Σ level times + 0.15 s × melee hits
- combo damage = hit damage × damage multiplier × hits, with the last level's hits × 2 (melee) or × the area attack's last-chain multiplier
- DPS = combo damage / cycle
- bow: shot time = max(draw, release animation), draw = m_drawDurationMin × (1 − 0.8 × skill / 100)
- crossbow: shot time = fire animation + reload + "reload done" animation (1.15 s), reload = m_reloadTime × (1 − 0.5 × skill / 100)
- each hit rolls × [n − 0.15, n + 0.15], clamped to [0, 1], n = 0.4 + 0.6 × skill / 100 (× 0.85–1 at skill 100)

The tables group weapons by category, with the skill each trains, lowest primary DPS first; a weapon's secondary
attack is in the same row. They use quality 1 (not upgraded; each item page has DPS per quality), a skill roll of 1 (every hit connects at full damage) and the sum of the weapon's damage
types, leaving out any type more than half of all creatures are immune to or ignore: chop and pickaxe, and spirit,
which is marked *. Staffs that fire in bursts or beams and thrown spears (the
spear has to be picked up again) aren't listed. Nor is the Butcher Knife, which only hits tamed creatures.

> Inferred: times are computed from the animator data, not measured in game; transition blending and input latency
> (about one frame) aren't counted. Bows assume the next draw starts the moment the arrow is released.

## Melee, staffs and throwables

{{weapons}}

## Bows and crossbows

Speed only: damage per shot is the weapon's plus the ammo's, so DPS depends on the arrows or bolts used. A bow's
damage scales with the draw fraction, so releasing early (once the release animation allows) trades damage for
speed one for one, with slower, less accurate arrows.

{{weapons-ranged}}
