---
title: Frost
summary: How frost damage slows, for how long, and who it doesn't slow.
order: 4
sources: Character.RPC_Damage; Character.AddFrostDamage; SE_Frost.AddDamage; SE_Frost.ModifySpeed; SEMan.ApplyStatusEffectSpeedMods; Character.UpdateWalking; Character.UpdateSwimming; HitData.DamageModifiers.ShouldOverride
---

Frost is dealt once, like physical damage, with no damage over time. After resistances and armor, any
frost left on a hit applies the [Frost](effect:Frost) effect, which cuts movement speed (walking, running,
swimming). Attack speed is unchanged. The effect doesn't stack: a new hit restarts it only when its duration
would be longer than the time left. Creatures immune to frost never get the effect. Resistant, very resistant and
slightly resistant ones get it but aren't slowed.

- duration $= min(1, frost / max health) × T$, $T$ = 50 s for creatures, 15 s for players
- speed $= 1 - (1 - 0.1 / m)(1 - t^2)$, $t$ = share of the duration gone, $m$ = 1 for Normal, 1.25 slightly weak, 1.5 weak, 1.75 very weak
- not slowed: immune, very resistant, resistant, slightly resistant

{{frost-chart}}

The effect lasts longest on targets with little health: 88 frost slows a 1,000 hp creature for 4.4 s and anything with 88 hp
or less for the full 50 s. On players, any frost-resistant gear (wolf and lox capes, the Frost Resistance Mead: see
[gear with damage modifiers](mechanic:damage-types)) stops the slow. The [Wet](effect:Wet) effect makes a player weak to frost, but a
weakness never overrides a resistance from gear (`DamageModifiers.ShouldOverride`).

> Inferred: SE_Frost's multiplier list also has entries for the resistant levels, but ModifySpeed returns before it
> reads them, so they have no effect.

## Weapons and ammo

Frost at quality 1. The last column is how long one quality-1 hit slows a creature with 1,000 health and no frost
modifier.

{{frost-weapons}}

## Creatures weak to frost

They take more frost damage, so each hit slows them for longer, and they slow down more.

{{frost-weak}}

## Creatures that resist frost

Never slowed.

{{frost-resistant}}
