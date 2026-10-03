---
title: Adrenaline
summary: How the bar fills and drains; trinket effects when it is full.
order: 6
sources: Player.GetMaxAdrenaline; Player.UpdateModifiers; Player.AddAdrenaline; Player.UpdateStats; Player.RPC_HitWhileDodging; Player.ActivateGuardianPower; Attack.OnAttackTrigger; Attack.FireProjectileBurst; Attack.DoMeleeAttack; Attack.DoAreaAttack; Projectile.OnHit; Humanoid.BlockAttack; Character.AddStaggerDamage; Character.RPC_Damage; SE_Stats.ModifyAdrenaline
---

The bar holds the sum of the equipped items' max adrenaline; the player's own base is 0, so without a trinket nothing
fills. Gains count only while the bar is below max. At max, every equipped item with a full-adrenaline effect starts it
(or restarts its timer) and the bar empties; with no such item it stays full. Each gain restarts the decay delay; when
the delay runs out the bar drains every frame.

- gain $= v × rate × g(f) × (1 + Σm)$: $f$ = fill before the gain, $rate$ = world modifier (1 by default), $g$ = gain curve, $m$ = active effects' adrenaline modifier
- delay after a gain $= delay(f)$ seconds
- drain $= degen(f)$ per second, $f$ = current fill

{{adrenaline-chart}}

> Inferred: the chart and drain times interpolate the curves linearly between their keys; the dump has no tangents,
> so the game's curves may bend between keys.

## Gains

{{adrenaline-sources}}

## Trinkets

{{trinkets}}

## Weapons

Attacks that differ from the default (1 per melee or area hit, nothing on use):

{{adrenaline-attacks}}

Blockers that differ from the default (2 per block, 5 per parry):

{{adrenaline-blockers}}

## Effects

{{adrenaline-effects}}
