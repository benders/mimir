---
title: Forge of Potential
summary: Where the idol forge stands, and how refining with Battle and Protection Idols works.
order: 6
sources: ZoneSystem.GenerateLocationsTimeSliced; ZoneSystem.RemoveUnplacedLocations; InventoryGui.UpdateRecipeList; InventoryGui.UpdateRecipe; InventoryGui.DoCrafting; Player.RequiredCraftingStation; Player.HaveRequirements; Player.ConsumeResources; Piece.Requirement.GetAmount
---

An ancient forge among broken statues of Thor and Freya in the Mountains. It can't be built: there is
one per world. It takes the Battle Idols (weapons) and Protection Idols (armor) found in chests and Hildir's Plains
fortress to refine gear one quality level at a time, past the level a normal station stops at, at the risk of
destroying it. Each tier of gear asks for the idol of its material.

{{forge-placement}}

At the forge the crafting menu lists only items you carry that can be upgraded and whose recipe names an idol. The
recipe's station and station level don't apply, and only the idol is charged: one per attempt, used up whatever happens.
Normal stations ignore the idol. A failed attempt destroys the item and gives back part of its materials (never the
idol).

- outcome: roll r in [0, 1); r ≤ chance → +1 level; else breakChance ≥ 1 − r → the item breaks; else −1 level
- returned per recoverable material $= ⌈(amount + cost(q - 1)) × breakReturn⌉$, $q$ = the quality aimed for, cost as on [item upgrades](mechanic:item-upgrades)
- attempt time $= 8 + q$ s
- chance of $n$ levels in a row $= chance^n$

> Inferred: the attempt time uses InventoryGui's code defaults (m_upgraderDuration 8, m_upgraderDurationPerLevel 1);
> the GUI prefab isn't in the dump, so its inspector values are unchecked.

## Idols

{{forge-idols}}

{{forge-streak}}

{{forge-return-example}}

## What each idol upgrades

{{forge-items}}
