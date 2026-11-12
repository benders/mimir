---
title: Taming
summary: Taming, feeding, breeding and riding creatures, and what changes once they are tame.
sources: Tameable.TamingUpdate; Tameable.DecreaseRemainingTime; Tameable.GetTameness; Tameable.IsHungry; Tameable.OnConsumedItem; Tameable.Interact; Tameable.RPC_Command; Tameable.UpdateSavedFollowTarget; Tameable.SetName; Tameable.UseItem; Tameable.OnDeath; MonsterAI.UpdateAI; MonsterAI.UpdateTarget; MonsterAI.OnDamaged; MonsterAI.SetTarget; MonsterAI.MakeTame; MonsterAI.UpdateConsumeItem; MonsterAI.FindClosestConsumableItem; BaseAI.UpdateRegeneration; BaseAI.IsEnemy; BaseAI.IdleMovement; BaseAI.Follow; BaseAI.AvoidFire; BaseAI.CanSenseTarget; BaseAI.GetTimeSinceSpawned; BaseAI.RPC_OnNearProjectileHit; Procreation.Procreate; Procreation.ReadyForProcreation; Procreation.IsDue; SpawnSystem.GetNrOfInstances; Growup.GrowUpdate; EggGrow.GrowUpdate; EggGrow.CanGrow; Sadle.Interact; Sadle.ApplyControlls; Sadle.RPC_Controls; Sadle.UpdateRiding; Sadle.UpdateStamina; Sadle.UpdateDrown; Sadle.UpdateRidingSkill; Sadle.RPC_RequestControl; Sadle.RPC_RemoveSaddle; MovementDamage.Update; Attack.DoMeleeAttack; Attack.DoAreaAttack; Projectile.IsValidTarget; Aoe.ShouldHit; TeleportWorld.Teleport
---

A wild creature tames itself while it is fed and calm. Every 3 s the client that owns it takes 3 s off its taming
time, if it has eaten within its fed time and isn't alerted. The time left is saved with the creature, so progress
survives leaving and coming back, but it only runs while a player is near enough to keep it loaded. Nothing resets it.
A creature is alerted when it sees an enemy (you) closer than its alert range (shorter while you sneak), when it is
hurt, when a projectile lands near it, or, if it is afraid of fire, within 3 m of one. It calms down after 30 s without
sensing its target or 60 s without attacking. Hover over it to see the tameness in percent. The first tick also clears
the creature's despawn flags, so a raid creature or one that leaves at daybreak stays once you start.

- taming time $= T$ (`m_tamingTime`), ticks of 3 s, each ×2 for every player within 60 m under a TamingBoost effect
  (below): 2 such players make it 4×
- hungry when more than `m_fedDuration` s of world time have passed since the last meal; a creature that never ate is hungry

{{tame-boost}}

{{tame-list}}

Staff summons (spirit caller creatures, the Dead Raiser's skeletons) start tame and can't breed, so they are left out.

## Once tame

A tame creature isn't an enemy of players, other tames, or Dvergr that aren't angry. Group comes first: a tame and a
wild creature of the same group (a tame and a wild boar) ignore each other. Every other creature is an enemy, so wild
creatures and raids attack tames and tames fight back. A tame never attacks buildings, isn't afraid of fire and doesn't
flee wards. It gives up a target that is more than its alert range from the player it follows, or from where it was
told to stay. With the passive mobs world modifier, a tame only notices creatures that are already alerted.

- use: pet it; a commandable tame (wolf) toggles follow / stay instead
- follow: stops within 3 m of the player, runs when more than 10 m behind; remembered by player name, so it follows
  again when that player comes back. Stay: it wanders around that spot. Others wander around where they stand.
- alt-use: rename (10 characters)
- players hurt tames only with PvP on (melee, area, projectiles); area effects that hit friends hurt them anyway;
  damage numbers show on tames
- portals carry players only
- death: the usual drops, plus its saddle

## Food and healing

A hungry creature looks for food every 10 s: the closest item from its list lying on the ground within its search
range that it can walk to. It walks up, eats one from the stack and is fed again. It doesn't take food from chests or
item stands, doesn't eat while alerted with a target, and doesn't look while it is fed. Eating doesn't heal. Like every
creature it regenerates its maximum health over an hour of world time ([creature healing](mechanic:healing)), but a
hungry tame doesn't regenerate at all. Hunger also stops taming and breeding and slows a mount's stamina.

- regeneration while fed $= max health / 3600$ per s of world time, also while away or asleep; none while hungry
- fed time is world time, so a night's sleep uses part of it

## Breeding

Every `interval` s, the client that owns a tame runs a breeding check. A pregnant tame gives birth at the first check
more than its pregnancy time (world time) after it became pregnant. Otherwise the check adds a love point, unless one
of these stops it: a random roll fails, or the tame is alerted or hungry. It also needs fewer than the cap of its kind
and its young within the range, and at least 2 of its kind ready to breed (itself included: tame, fed, not pregnant)
within the partner range. Enough love points make it pregnant.

- love point per check: chance $1 - p$, $p$ = `m_pregnancyChance` (the game returns early when a roll is at most $p$)
- average time to a birth $= points × interval / (1 - p) + (⌊pregnancy / interval⌋ + 1) × interval$
- the young is tame, with the mother's stars (at least `m_minOffspringLevel`); the father's don't count
- a pregnant partner isn't ready, so a lone pair takes turns; a third one lets two carry at once
- the cap counts adults and the direct young (piglets, cubs, calves; for hens and asksvin the eggs, not the chicks and
  hatchlings) within the range around the one checking, wild ones included

{{tame-breeding}}

A pen needs partners within the partner range, and the young moved out before the cap is reached. Young grow up after
their grow time of world time since they were born, keeping their stars and tameness. Nothing else counts: no fire,
roof, food or company, and a young creature away from players catches up as soon as it is loaded again. Eggs are the
only young with conditions: they hatch only while they lie alone, not stacked, and warm, inside a fire's heat area
([areas](mechanic:player-base)), and for hen eggs also under a roof with enough cover (the egg's page gives the share). The time restarts whenever
that stops. The hatchling is tame with the egg's quality as its level. Chicks become hens that start tame.

- young: grows up when world time since spawned $>$ `m_growTime`, checked every 10 s while loaded
- egg: hatches when it has met its conditions without a break for `m_growTime` s of world time, checked every 5 s

> Inferred: dropped eggs count toward the cap. For an item, SpawnSystem.GetNrOfInstances counts objects tagged
> `spawned`; whether a laid egg carries that tag isn't in the decompiled code.

## Saddles

Use a saddle on a tame mount to put it on. Use the saddle to ride; alt-use removes it when nobody is riding. The rider's
client becomes the mount's owner, and only one player rides at a time.

- controls: forward walks, run runs, back stops, block stands still and turns; it heads where you look
- stamina: running on land costs the run drain per s and swimming the swim drain, × $1 - 0.5 × Ride/100$; without
  stamina it walks, and while it swims with none it drowns for $⌈max health / 20⌉$ per s
- refill: $r × (2 - s / max)$ per s ($r$ = regen, lower when hungry), 1 s after use, not while swimming or attacking;
  from empty that is $max × ln 2 / r$
- the Ride skill rises once per second of running

{{tame-saddles}}

A running lox or moose hits what it runs into (Running hits, per creature below).

## Butcher Knife

A weapon flagged `m_tamedOnly` only hits tame creatures, PvP or not, and nothing else. They drop what they would drop
otherwise, stars included.

{{tame-knives}}

## Each tame

{{tame Boar}}

{{tame Wolf}}

{{tame Hen}}

{{tame Lox}}

{{tame Asksvin}}

{{tame Moose}}
