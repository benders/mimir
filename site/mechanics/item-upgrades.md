---
title: Item upgrades
summary: Stats per quality, upgrade cost, station level.
order: 5
sources: ItemDrop.ItemData.GetDamage; ItemDrop.ItemData.GetArmor; ItemDrop.ItemData.GetMaxDurability; ItemDrop.ItemData.GetBaseBlockPower; ItemDrop.ItemData.GetDeflectionForce; Piece.Requirement.GetAmount; Recipe.GetRequiredStationLevel; InventoryGui.UpdateRecipeList; InventoryGui.UpdateRecipe; InventoryGui.SetupRequirementList
---

Each quality level above 1 adds the per-level value to every stat. The cost of quality $q$ is not cumulative: each
step pays only for its own level. Upgrader resources add the recipe amount on top and are asked for only at an Upgrade
Station, which lists items of any quality and asks for station level 1. Values assume world level 0.

- stat $= base + perLevel × (q - 1)$ (damage, armor, durability, [block](mechanic:blocking), parry force)
- cost $= amount$ at $q = 1$; $⌊(q - 1) × perLevel⌋$ for $q ≤ 3$; $⌊(4 + (q - 4)/2) × perLevel⌋$ for $q ≥ 4$
- station level $= max(1, minStationLevel) + q - 1$

{{chart upgrade}}

{{upgrade-costs}}

{{upgrade-example}}
