---
title: Damage types and resistances
summary: The damage types, what Weak, Resistant and Immune multiply, how armor reduces damage, and the order a hit is processed in.
order: 4
sources: HitData.DamageTypes; HitData.DamageType; HitData.DamageModifier; HitData.ApplyModifier; HitData.ApplyResistance; HitData.DamageModifiers.Apply; HitData.DamageModifiers.ShouldOverride; HitData.DamageTypes.ApplyArmor; Character.RPC_Damage; Character.GetDamageModifiers; Character.ApplyDamage; Player.ApplyArmorDamageMods; Player.GetBodyArmor; SEMan.ApplyDamageMods; DamageText.ShowText
---

## Damage types

A hit carries one number per damage type (`HitData.DamageTypes`):

- **Physical:** blunt, slash, pierce.
- **Tool:** chop and pickaxe. These only matter against trees, rocks and ore; almost every creature in the data
  ignores them.
- **Elemental:** fire, frost, lightning.
- **Other:** poison, spirit, and a generic `damage` value that has no resistance of its own. The game also has a
  non-player type (`m_nonPlayer`).

Creatures, armor, shields and status effects carry a *damage modifier* for each type except the generic one
(`HitData.DamageModifiers`). The generic `damage` value is never changed by resistances (`HitData.ApplyResistance`
does not touch it).

## What the modifiers do

`HitData.ApplyModifier` multiplies the damage of one type by a factor that depends on the modifier:

| Modifier | Multiplier |
|---|---:|
| Very weak | ×2 |
| Weak | ×1.5 |
| Slightly weak | ×1.25 |
| Normal | ×1 |
| Slightly resistant | ×0.75 |
| Resistant | ×0.5 |
| Very resistant | ×0.25 |
| Immune | ×0 |
| Ignore | ×0 |

Immune and Ignore both remove the damage. They differ in feedback: damage is sorted into four groups (normal, resistant,
weak, immune) by its modifier, and the group that held the most damage before the modifiers decides the *significant
modifier* handed to `ApplyDamage`, which picks the look of the damage number (`DamageText.ShowText`). Immune damage
counts toward the immune group, Ignore damage toward none. The site shows Ignore as Immune, and leaves out the chop and
pickaxe rows that almost every creature has.

A target that is Immune to fire, frost, lightning or poison also does not get the matching status effect (burning,
frost, lightning, poison) from a hit (`Character.RPC_Damage`).

### Which modifier applies

A creature uses its own modifiers, except that a hit on a weak spot uses that weak spot's modifiers instead
(`Character.GetDamageModifiers`). Players start from the modifiers on the Player prefab (`Character.m_damageModifiers`). On top of that, the modifiers of equipped chest,
legs, helmet and cape items (`Player.ApplyArmorDamageMods`), and then of active status effects (`SEMan.ApplyDamageMods`),
are applied one at a time with `DamageModifiers.Apply`.

Modifiers do **not** multiply together. Each new modifier either replaces the current one or is dropped
(`DamageModifiers.ShouldOverride`). The new modifier `b` replaces the current `a` unless:

- `a` is Ignore (it can never be replaced);
- `b` is a weaker level of the same direction: Resistant after Very resistant, Slightly resistant after Resistant or
  Very resistant, and the same for the weak levels;
- `a` is Resistant, Very resistant, Slightly resistant or Immune, and `b` is any weak level.

Immune always replaces anything but Ignore. The rule has two consequences. First, wearing two pieces that are both Resistant
to fire gives Resistant, not Very resistant. Second, the rule depends on order: a Resistant modifier applied after
an Immune one replaces it, and a resistance beats a weakness whichever came first.

## Armor

Armor applies to players only (`Character.RPC_Damage`: `hit.ApplyArmor(GetBodyArmor())` when `IsPlayer()`). Creatures
have no armor, apart from a fixed amount that depends on the world level setting. The player's armor is the sum of the
armor of the equipped chest, legs, helmet and cape items (`Player.GetBodyArmor`), each worth `armor + armorPerLevel × (quality - 1)`,
plus any status effect armor modifiers.

The armor formula is the same piecewise one that blocking uses (`HitData.DamageTypes.ApplyArmor`). With total damage
$D$ and armor $A$:

- if $A < D/2$: damage taken $= D - A$
- otherwise: damage taken $= D² / (4A)$

$D$ is the sum of blunt, slash, pierce, fire, frost, lightning, poison, spirit and non-player damage after
resistances. Chop, pickaxe and the generic `damage` value are not reduced by armor. All types in $D$ are scaled by the
same factor. Zero or negative armor changes nothing. The first branch is a flat subtraction and the second is
a fraction that shrinks as armor grows but never reaches zero, so armor has diminishing returns:

{{chart armor}}

Against a 60-damage hit, armor 30 already halves the damage taken (30), and each doubling after that halves it again
(15 at armor 60, 7.5 at armor 120). Against a 120-damage hit, armor 30 only takes off 30; it takes armor 60 to halve it.

## The order of a hit

In `Character.RPC_Damage`, a hit on a character is processed in this order (steps that do not apply to a given target are
skipped):

1. Damage dealt by creatures is scaled by the difficulty settings (`GetDifficultyDamageScalePlayer`,
   `m_enemyDamageRate`).
2. The backstab bonus applies to an unalerted creature (at most once per 300 seconds per creature), and a staggered
   creature takes ×2.
3. **Block** ([Blocking](mechanic:blocking)), if the defender is blocking.
4. **Resistances**: the modifiers described above (`ApplyResistance`).
5. **Armor**, for players (`ApplyArmor`).
6. Fire, poison and spirit damage are taken out of the direct hit and applied through status effects (`AddFireDamage`,
   `AddPoisonDamage`, `AddSpiritDamage`). Frost and lightning stay in the direct hit and are also passed to
   `AddFrostDamage` and `AddLightningDamage`.
7. In `ApplyDamage`, creatures take the player-count scaling (`GetDifficultyDamageScaleEnemy`) and the world's
   player damage rate; players take their damage-taken rate. Then health is reduced.

## Creatures with notable resistances

Generated from the game data: creatures that are Immune, Very resistant or Very weak to some type. Other
modifiers are on each creature's page.

{{resistant-creatures}}

## Gear with damage modifiers

{{resistant-gear}}

> Inferred: `data/` holds each prefab's own modifiers. A creature's effective modifier on a given hit can still
> differ, because of weak spots and status effects that carry modifiers, as described above.
