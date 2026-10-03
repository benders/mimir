---
title: Blocking
summary: Block power, parrying, what gets through a block, stamina, stagger and shield durability.
order: 1
sources: Humanoid.BlockAttack; Humanoid.GetCurrentBlocker; Humanoid.UpdateBlock; ItemDrop.ItemData.GetBlockPower; ItemDrop.ItemData.GetBaseBlockPower; ItemDrop.ItemData.GetDeflectionForce; Skills.GetSkillFactor; Skills.GetSkillLevel; HitData.DamageTypes.ApplyArmor; HitData.ApplyResistance; HitData.BlockDamage; Character.RPC_Damage; Character.AddStaggerDamage; Character.UpdateStagger; SE_Stats.ModifyTimedBlockBonus
---

## What can be blocked

A defender blocks with the item in the left hand (a shield), or with the current weapon if the left hand is empty
(`Humanoid.GetCurrentBlocker`). A hit is only checked for blocking when it is marked blockable and the defender is
holding the block (`Character.RPC_Damage`: `hit.m_blockable && IsBlocking()`). Some attacks are not blockable.

`Humanoid.BlockAttack` returns without blocking when the hit comes from behind: it compares the hit direction with
the way the defender faces (`Vector3.Dot(hit.m_dir, transform.forward) > 0`). That is the only direction check in the method.

## Block power

$B = (block + blockPerLevel × (quality - 1)) × (1 + 0.5 × skill/100)$

- `block` and `blockPerLevel` are the shield's own values (`GetBaseBlockPower`: `m_blockPower + max(0, quality - 1) * m_blockPowerPerLevel`).
- The skill term is `GetBlockPower`: `base + base * skillFactor * 0.5`. The skill factor is the Blocking level, floored
  and clamped to 0 to 100, divided by 100 (`Skills.GetSkillLevel`, `Skills.GetSkillFactor`). Status effects can change
  the level before it is floored. A maxed skill is therefore +50% block power.
- Higher quality adds `blockPerLevel` once per level above 1. Item stats on shield pages use the same quality rule.

### Parry

A hit lands as a parry when the shield has a parry bonus above 1 and the block was raised less than 0.25 seconds
earlier (`m_timedBlockBonus > 1f && m_blockTimer != -1f && m_blockTimer < 0.25f`; `Humanoid.UpdateBlock` restarts the
timer at 0 each time the block is raised). A parry multiplies the block power by the shield's parry bonus. Status
effects with a timed block bonus multiply it again, by `1 + bonus` (`SE_Stats.ModifyTimedBlockBonus`).

Shields without a parry bonus above 1 cannot parry. The table below shows which ones those are (the tower shields
among them).

## What gets through

The shield's own damage modifiers are applied to the hit first (`modifiers.Apply(m_damageModifiers)` then
`hit.ApplyResistance`), so a shield that is Resistant to a damage type halves that damage before block power is
considered. The Serpent Scale Shield does this for pierce.

Block power is then used like armor on a copy of the hit (`HitData.DamageTypes.ApplyArmor`). The *blockable damage*
$D$ is the sum of blunt, slash, pierce, fire, frost, lightning, poison, spirit and the non-player type (`GetTotalBlockableDamage`;
chop and pickaxe are not included). With block power $B$:

- if $B < D/2$: damage through $= D - B$
- otherwise: damage through $= D² / (4B)$

Every damage type is scaled by the same factor, so the mix of damage types is unchanged. Nothing ever gets through as
exactly zero, but a high block power makes it small.

{{chart block}}

The amount removed is `blocked = D - through`. If the block holds, `HitData.BlockDamage` scales every blockable damage
type down so that the total falls by that amount. The rest of the hit then continues through the normal damage
pipeline: in `Character.RPC_Damage` the block comes **before** the defender's own damage modifiers and, for players,
body armor (`ApplyResistance`, then `ApplyArmor(GetBodyArmor())`). Block power and armor therefore both apply to the
same hit, one after the other.

## Stamina

Blocking costs `Humanoid.m_blockStaminaDrain` times `clamp01(blocked / B)`, then changed by the
equipment's block stamina modifier. The Player prefab sets `m_blockStaminaDrain` to 10 (the field default in the code is
25) and `m_perfectBlockStaminaDrain` to 0, so as the player:

$stamina = 10 × clamp01(blocked / B)$

A parry costs `m_perfectBlockStaminaDrain` instead, which is 0 for the player. If the shield defines
`m_perfectBlockStaminaRegen`, a successful parry gives back that much stamina (this field is not in `data/` yet).

> Inferred, by algebra from the two formulas above and not checked in the game: with $x = D/B$ the stamina fraction is
> $x - x²/4$ up to $x = 2$ and exactly 1 beyond it, so a block never costs more than 10 stamina and the cost per
> point of damage is highest for small hits.

## Stagger and failed blocks

The damage that got through the block (blunt, slash, pierce and lightning only,
`GetTotalStaggerDamage` on the armored copy) is added to the defender's stagger bar (`Character.AddStaggerDamage`). The
bar fills to `maxHealth × m_staggerDamageFactor`, which is 0.4 on the Player prefab, and drains by a fifth of that
threshold per second (`Character.UpdateStagger`). When the bar fills the defender is staggered and the block **fails**.

The block also fails if the defender is out of stamina after paying for it. In both cases `BlockDamage` is not
called: the whole hit continues to resistances and armor. The stamina, shield durability and skill gain of the attempt
are still spent.

## Durability and skill

Each block costs the shield `m_useDurabilityDrain × D / B` durability (D is the blockable damage after the shield's own
modifiers, before block power), times the world durability rate. Blocking raises the Blocking skill by 1 per
block and 2 per parry (the amount passed to `RaiseSkill`).

## Pushback

When a block holds, the push force of the hit is scaled by the blocked fraction. For a melee hit the attacker is
pushed back by the shield's deflection force (the item's *parry force*, `GetDeflectionForce`: `m_deflectionForce +
(quality - 1) * m_deflectionForcePerLevel`) times `1 - clamp01(fraction / 2)`. It depends on the shield's quality, not
on the Blocking skill. A parry also staggers the attacker if it can be staggered by blocks (`m_staggerWhenBlocked`, true
by default).

## Shields

Block power for every shield at the given skill. "Parried" is the power of a parry at skill 100 and maximum quality.

{{shields}}
