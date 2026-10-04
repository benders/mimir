---
title: Skills
summary: Experience per level, what raises each skill, Rested, death penalty.
order: 10
sources: Skills.Skill.Raise; Skills.Skill.GetNextLevelRequirement; Skills.RaiseSkill; Player.RaiseSkill; SE_Stats.ModifyRaiseSkill; Skills.GetSkillLevel; Skills.OnDeath; Skills.LowerAllSkills; Player.OnDeath; Player.HardDeath; Attack.DoMeleeAttack; Attack.DoAreaAttack; Projectile.OnHit; Humanoid.BlockAttack; Player.Dodge; Player.RPC_HitWhileDodging; Player.CheckRun; Player.OnSwimming; Player.OnSneaking; Character.Jump; InventoryGui.DoCrafting; InventoryGui.RepairOneItem; Player.UpdatePlacement; CookingStation.OnInteract; Pickable.Interact; FishingFloat.FixedUpdate; Sadle.UpdateRidingSkill
---

Each raise adds experience; at the next level's requirement the level goes up by one and the experience resets to 0,
so any excess is lost. Levels stop at 100. Effects such as [Rested](effect:Rested) add to the raise; dodging ignores
them. A death more than 10 minutes after the previous one lowers every skill by 5% of its level and clears its
progress; dying sooner costs nothing (the "No skill drain" effect).

- experience per raise $= step × a × (1 + Σ m) × w$: $step$ = the skill's gain step, $a$ = the raise amount, $m$ = effect modifiers, $w$ = world skill gain rate (1)
- next level needs $⌊L + 1⌋^{1.5} × 0.5 + 0.5$
- after a death: $L × (1 - 0.05)$
- weapons: $a$ = the attack's raise amount, once per attack that hits (melee: × 1.5 if it hit a creature)
- blocking 1 per block, 2 per parry; dodge 0.1 per dodge, 1 per perfect dodge
- run, swim, ride (at run speed), fishing (reeling): 1 per second; sneak 1 per second near enemies, else 0.1; jump 1 per jump
- crafting: 1 per item crafted at the station; repairing adds the share of durability restored; each piece built raises its tool's skill by 1
- cooking 0.4 per item put on, 0.6 per item taken off; picking 1 per harvest that has a skill

{{chart skills}}

## Raises per skill

{{skills}}

## Death penalty

{{death-penalty}}
