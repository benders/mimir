---
title: Drops
summary: Star multiplier, amount roll, pseudo-random countdown.
order: 2
sources: CharacterDrop.GenerateDropList; CharacterDrop.OnDeath; CharacterDrop.DropItems; Game.ScaleDrops; Character.CheckDeath; Character.CustomFixedUpdate; Game.FixedUpdate; Player.LateUpdate; ZNet.GetNrOfPlayers
---

Level-multiplied drops scale with stars: $n = 2^{stars}$ multiplies both chance and amount (cap 100). The amount is
`Random.Range(min, max)` on integers, max exclusive, so pages show min to max − 1. One-per-player drops give one per
connected player. At $p > 0.3$ (or with `NoPseudoDrops`) a drop is a plain roll; at $p ≤ 0.3$ a per-item countdown
replaces it: at most about $2/p$ kills between drops, shared by every creature dropping that item, reset when $p$
changes or the game restarts.

- chance $p = chance × n$
- amount $= Random.Range(min, max) × n$
- countdown after a drop: $Random.Range(0, ⌊2/p + 1⌋)$, −1 per kill, drops at ≤ 0

{{chart pseudo}}

{{pseudo-table}}

> Inferred: the owner of the creature rolls the drop, so near players the counters live on clients, not the server.

## Troll at 0–2 stars

{{drops-example}}

## Low-chance drops

{{pseudo-drops}}
