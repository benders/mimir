---
title: Drops
summary: Star multiplier, amount roll, pseudo-random countdown.
sources: CharacterDrop.GenerateDropList; CharacterDrop.OnDeath; CharacterDrop.DropItems; Game.ScaleDrops; Character.CheckDeath; Character.CustomFixedUpdate; Game.FixedUpdate; Player.LateUpdate; ZNet.GetNrOfPlayers
---

Level-multiplied drops scale with stars: $n = 2^{stars}$ multiplies the chance and, except for trophies, the amount
(cap 100). The amount is `Random.Range(min, max)` on integers, max exclusive, so pages show min to max − 1 (the
resource-rate world modifier scales it). One-per-player drops give one per connected player. At $p > 0.3$ (or with
`NoPseudoDrops`) a drop is a plain roll; at $p ≤ 0.3$ a countdown replaces it: at most about $2/p$ kills between drops,
one countdown per item and chance, shared by every creature dropping that item at that chance, lost when the game
restarts.

- chance $p = chance × n$
- amount $= Random.Range(min, max) × n$ (trophies: $× 1$)
- first countdown: $Random.Range(0, ⌊2/p⌋)$; after a drop: $Random.Range(0, ⌊2/p⌋ + 2)$; −1 per kill, drops at ≤ 0

{{chart pseudo}}

{{pseudo-table}}

> Inferred: the owner of the creature rolls the drop, so near players the counters live on clients, not the server.

## Troll at 0–2 stars

{{drops-example}}

## Low-chance drops

{{pseudo-drops}}
