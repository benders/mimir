---
title: Drops
summary: How creature drops are rolled, how stars multiply them, and the pseudo-random scheme behind low chances.
order: 2
sources: CharacterDrop.GenerateDropList; CharacterDrop.OnDeath; CharacterDrop.DropItems; Game.ScaleDrops; Character.CheckDeath; Character.CustomFixedUpdate; Game.FixedUpdate; Player.LateUpdate; ZNet.GetNrOfPlayers
---

This page covers drops from creatures, which come from the `CharacterDrop` component. Trees, rocks, pickables and
chests use other code that is not covered here.

## What a drop entry holds

Each entry in a creature's drop list (`CharacterDrop.Drop`) has the item, a minimum and maximum amount, a chance,
and three flags: *level multiplier*, *one per player* and *don't scale*. Creature pages list the entries as Item, Amount
and Chance; a drop marked **×stars** has the level multiplier and one marked **×players** is one per player. The
flag *don't scale* is not in `data/` yet and has no effect unless the world's resource rate is changed (below).

When a creature dies, `CharacterDrop.OnDeath` calls `GenerateDropList`, then `DropItems` creates the items around the
creature's center with a random offset and a small random push.

## Stars multiply drops

Let $n = max(1, int(2^(level - 1)))$ where the level is the creature's level, one more than its stars
([Creature levels](mechanic:creature-levels)). So $n$ is 1 for an unstarred creature, 2 for one star, 4 for two stars
and 8 for three. For a drop with the level multiplier flag:

- the effective chance is $p = chance × n$ (it can exceed 100%, which just means "always");
- the amount is multiplied by $n$ after it is rolled.

Drops without the flag ignore stars. Trophies, for example, almost never scale. The rolled amount is capped at 100
(`if (num7 > 100) num7 = 100`), and a drop with a rolled amount of 0 or less drops nothing.

## The amount

The amount is `Random.Range(min, max)` on integers. Unity's integer `Random.Range` **excludes** the upper bound, so a drop
listed as 2 to 5 gives 2, 3 or 4, and one listed with equal minimum and maximum gives exactly that amount. This is
engine behavior, not visible in the decompiled code. Site pages therefore show a range as `min` to `max - 1`.

If the world's resource rate is not 1 (a world modifier), `Game.ScaleDrops` multiplies the rolled amount by it,
rounds it and keeps at least 1, using a float `Random.Range` whose upper bound is inclusive; a drop with *don't scale*
set uses the plain integer roll instead. Everything on this site assumes a resource rate of 1.

A *one per player* drop ignores the rolled amount and drops one item for every connected player
(`ZNet.GetNrOfPlayers` is the size of the player list).

## The roll

If the effective chance $p$ is above 0.3, or the world has the `NoPseudoDrops` global key, the drop is a plain roll: it
drops when `Random.value <= p`.

### Pseudo-random drops

If $p ≤ 0.3$ and `NoPseudoDrops` is not set, the roll is replaced by a countdown, so that bad luck cannot go on for
long. For each item the game keeps a counter, keyed by the item's prefab name, together with the chance it was
created for:

1. On a kill, if there is a counter for this item **and its stored chance equals the current $p$**, the counter goes down by 1.
   Otherwise the counter is set to `Random.Range(0, int(1/p × 2))`, a number from 0 up to about $2/p - 1$.
2. If the counter is 0 or below, the item drops, and the counter is set to `Random.Range(0, int(1/p × 2 + 1))`, a number from 0
   up to about $2/p$. Otherwise the new value is stored and nothing drops.

So after a drop the next one comes after at most about $2/p$ kills, and the long-run rate is close to $p$ but not
exactly it (the integer cut-offs move it a little either way). For a 25% chance that is at most 8 kills (a counter of 8
is counted down by one per kill, and the item drops on the 8th) and 24.3% in the long run.

{{pseudo-table}}

Consequences that follow from the code:

- The counter is shared by every creature that drops the same item, because it is keyed by the item name.
- The counter resets when the chance changes. A creature whose drop has the level multiplier switches between chances at
  different star levels (for example 10% unstarred and 20% at one star), and each switch discards the counter.
- At three stars $n = 8$, so almost every low-chance drop with the multiplier flag is above 0.3 and uses the plain roll.
- The counters are kept in a static dictionary in the game process. Nothing in `CharacterDrop` saves them, so a restart of the game resets them.

> Inferred: the drop is rolled by whichever game instance owns the creature. `Character.CustomFixedUpdate` only runs
> `CheckDeath` (which calls `OnDeath`) for the owner of the creature's network object, and `Game.FixedUpdate` parks the
> reference position of the game instance at (1000000, 0, 1000000), and only a local player moves it (`Player.LateUpdate`
> sets it to the player's own position), which a dedicated server does not have. From that the creatures near players
> should be owned by clients, so the pseudo-random counters would live in the clients, not on the server. This was read
> from the code, not tested on a server.

## Example from the data

The Troll's drop list at 0, 1 and 2 stars, computed with the rules above from `data/`. Amounts are shown from the
smallest to the largest possible total.

{{drops-example}}

## Low-chance drops in the game

{{pseudo-drops}}
