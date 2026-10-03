---
title: Item upgrades
summary: What each quality level adds to an item's stats, what an upgrade costs, and the station level it needs.
order: 5
sources: ItemDrop.ItemData.GetDamage; ItemDrop.ItemData.GetArmor; ItemDrop.ItemData.GetMaxDurability; ItemDrop.ItemData.GetBaseBlockPower; ItemDrop.ItemData.GetDeflectionForce; Piece.Requirement.GetAmount; Recipe.GetRequiredStationLevel; InventoryGui.UpdateRecipeList; InventoryGui.UpdateRecipe; InventoryGui.SetupRequirementList
---

An item's *quality* is its upgrade level, starting at 1. Item pages show the stats for every quality up to the item's
maximum, and the cost of each step in the Crafting section.

## Stats

Quality adds a fixed amount per level above the first, for each stat (`ItemDrop.ItemData`):

| Stat | Formula | Method |
|---|---|---|
| Damage, per type | damage + damagePerLevel × (quality - 1) | `GetDamage` |
| Armor | armor + armorPerLevel × (quality - 1) | `GetArmor` |
| Durability | durability + durabilityPerLevel × (quality - 1) | `GetMaxDurability` |
| Block power | block + blockPerLevel × (quality - 1) | `GetBaseBlockPower` ([Blocking](mechanic:blocking)) |
| Parry force | parryForce + parryForcePerLevel × (quality - 1) | `GetDeflectionForce` |

The world level setting adds more damage and armor on top; this page and the item pages assume world level 0.

## Cost of an upgrade

Getting an item to quality $q$ costs the amount of each resource given by `Piece.Requirement.GetAmount(q)`. It is not
cumulative: upgrading from quality 2 to 3 pays only for quality 3.

- $q = 1$ (crafting the item): the recipe's `amount`.
- $q = 2$ or $3$: $(q - 1) ×$ `amountPerLevel`.
- $q ≥ 4$: $(4 + (q - 4) / 2) ×$ `amountPerLevel`.

The result is rounded down. The step from quality 3 to 4 is the biggest, because the multiplier doubles from 2 to 4,
and from there it grows by half an `amountPerLevel` per level:

{{upgrade-costs}}

{{upgrade-example}}

A requirement with the *upgrader* flag adds the recipe's `amount` on top from quality 2 up (the result is
$⌊multiplier × amountPerLevel + amount⌋$), and it is only asked for at an Upgrade Station (below).

## Station level

The station level needed for quality $q$ is $max(1, minStationLevel) + q - 1$ (`Recipe.GetRequiredStationLevel`), so every
upgrade needs a station one level higher than the one before. The recipe's station is also where the upgrade is done.

## The Upgrade Station

At a crafting station that is marked as an upgrader (`m_upgrader`), the recipe list shows items of any quality, including
items already at their maximum quality, and only the requirements flagged as upgrader resources are asked for; at
other stations those are left out (`InventoryGui.UpdateRecipeList`, `InventoryGui.SetupRequirementList`). The station
level asked for is 1 there (`InventoryGui.UpdateRecipe`).

> Inferred: from these checks an Upgrade Station can take an item past its normal maximum quality. The code shows the item
> is listed and craftable; whether the extra levels do anything for the stats beyond the formulas above was not checked
> in the game.
