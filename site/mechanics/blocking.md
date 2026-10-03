---
title: Blocking
summary: Block power, parry, damage through, stamina, stagger, durability.
order: 1
sources: Humanoid.BlockAttack; Humanoid.GetCurrentBlocker; Humanoid.UpdateBlock; ItemDrop.ItemData.GetBlockPower; ItemDrop.ItemData.GetBaseBlockPower; ItemDrop.ItemData.GetDeflectionForce; Skills.GetSkillFactor; Skills.GetSkillLevel; HitData.DamageTypes.ApplyArmor; HitData.ApplyResistance; HitData.BlockDamage; Character.RPC_Damage; Character.AddStaggerDamage; Character.UpdateStagger; SE_Stats.ModifyTimedBlockBonus
---

The left-hand item blocks, else the weapon; hits from behind and unblockable attacks are not blocked. A raise within
0.25 s is a parry if the shield's parry bonus is above 1. The shield's own modifiers apply first, then block power
works like armor on the blockable damage $D$ (no chop/pickaxe); what gets through continues to resistances and body
armor. Damage through (blunt, slash, pierce, lightning) fills the stagger bar (0.4 × max health); a full bar or empty
stamina fails the block and the whole hit lands.

- block power $B = (block + blockPerLevel(q-1)) × (1 + 0.5 × skill/100)$, × parry bonus on a parry
- through $= D - B$ if $B < D/2$, else $D^2/4B$
- stamina $= 10 × clamp01(blocked / B)$; parry 0
- durability $= drain × D/B$; skill +1 per block, +2 per parry

{{chart block}}

{{chart stamina}}

## Shields

{{shields}}
