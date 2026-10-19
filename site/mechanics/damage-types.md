---
title: Damage types and resistances
summary: Modifier multipliers, override rule, armor formula, hit order.
order: 4
sources: HitData.DamageTypes; HitData.DamageType; HitData.DamageModifier; HitData.ApplyModifier; HitData.ApplyResistance; HitData.DamageModifiers.Apply; HitData.DamageModifiers.ShouldOverride; HitData.DamageTypes.ApplyArmor; Character.RPC_Damage; Character.GetDamageModifiers; Character.ApplyDamage; Player.ApplyArmorDamageMods; Player.GetBodyArmor; SEMan.ApplyDamageMods; DamageText.ShowText; HitData.DamageModifiers.ApplyIfBetter
---

Each hit carries one value per damage type: blunt, slash, pierce (physical); chop, pickaxe (tools); fire, frost,
lightning, poison, spirit; plus a generic `damage` no resistance touches. Modifiers do not stack: applied in order
(base, or a weak spot's own set → armor pieces → status effects), each new modifier replaces the current one unless it
is a weaker step in the same direction, a weakness after any resistance or Immune, or the current one is Ignore
(`DamageModifiers.ShouldOverride`); a later resistance does replace Immune. A creature's own Immune to fire, frost,
lightning or poison also blocks that status effect.

Armor $A$ applies after block and resistances: a player's armor pieces, or for creatures only at world level $w > 0$,
$A = 60w$ (`Game.m_worldLevelEnemyBaseAC`). $D$ = blunt + slash + pierce + elemental + poison + spirit after
resistances; tool and generic damage are not reduced.

| Modifier | ×damage |
|---|---:|
| Very weak | 2 |
| Weak | 1.5 |
| Slightly weak | 1.25 |
| Normal | 1 |
| Slightly resistant | 0.75 |
| Resistant | 0.5 |
| Very resistant | 0.25 |
| Immune, Ignore | 0 |

- taken $= D - A$ if $A < D/2$
- taken $= D^2 / 4A$ otherwise
- hit order: difficulty and world damage rate (creature attackers) → backstab × the weapon's bonus → staggered target ×2 →
  [block](mechanic:blocking) → resistances → armor → fire/poison/spirit to DoT

{{chart armor}}

## Notable resistances

{{resistant-creatures}}

## Gear with damage modifiers

{{resistant-gear}}
