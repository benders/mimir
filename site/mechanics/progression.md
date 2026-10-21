---
title: Progression stages
summary: The biome where you first get each item, creature and piece, and the site's stage filter.
sources: SpawnSystem.UpdateSpawnList; OfferingBowl.UseItem; Aoe.Setup; HitData.CheckToolTier; RandEventSystem.HaveGlobalKeys; Trader.UseItem; TriggerPersistentEventOnDestroy; CraftingStation.GetLevel; StationExtension.FindExtensions; MineRock.RPC_Hit; MineRock5.RPC_Damage; TreeBase.RPC_Damage; Destructible.RPC_Damage; ZoneSystem.GetKeyValue
---

Each entry's stage is the first biome, in order, where a player can get it. A way of getting something counts at the
latest stage among what it needs, and the entry takes its earliest way. A creature's stage is its earliest spawn.
The header's "Up to" filter hides later entries from indexes, search and "Used in" lists. A detail page past the
filter shows a spoiler warning.

- world spawn, vegetation, location, trader: the earliest of its biomes. The open sea counts from the start, and
  ocean next to land counts as that land (shipwrecks).
- recipe: its ingredients and its station, with an extension for each level above 1. Extensions of the same kind
  don't stack.
- smelting and other processing: the input, the station and the fuel.
- rock, tree, log, destructible: a player tool of its minimum tier that deals damage it isn't immune to (an explosion
  counts at its own tier: Dynamite). Bare hands do when the minimum tier is 0 and it takes weapon damage.
- boss: its offering (OfferingBowl), like a key.
- global key: the earliest creature that sets it on death, or the item a trader takes for it (Hildir's chests).
  A boss's key opens the next stage, so a raid that needs it comes one stage later.
- boss drops (trophy, Hard Antler, Dragon Tear...): the stage the boss opens, like its key. What they make, such as the
  Artisan Table, comes with them.
- persistent event: the object whose destruction starts it (the Fimbulvinter orb).
  What ends it (Malicious Ice) comes with it.

> Inferred: the order of biomes is the game's intended route, not something the code enforces. Early Axes (axe heads
> from Meadows chests) are left out as a way to cut birch and oak, an unusual early route to Fine Wood.
> The Fimbulvinter event's spawn lists aren't in the data: Malicious Ice is taken to be placed by it because
> destroying one ends it.

Item and piece pages show a requirements tree: the way that gives the stage, then the same for each thing it needs,
down to world sources and spawns. When several ways share a stage: crafting, smelting and building first, then
gathering (trees, rocks, pickables), creature drops, loot from chests and props in locations, traders, and breaking
world pieces last. Something needed twice is expanded once, where it is shallowest.

{{stage-counts}}
