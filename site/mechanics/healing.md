---
title: Creature healing
summary: How creatures and bosses regenerate, while away and while players sleep.
sources: BaseAI.UpdateAI; BaseAI.UpdateRegeneration; BaseAI.GetWorldTimeDelta; Character.Heal; Character.RPC_Heal; ZNet.GetTime; EnvMan.SkipToMorning; EnvMan.UpdateTimeSkip; EnvMan.RescaleDayFraction; EnvMan.CalculateCanSleep; Game.UpdateSleeping; Attack.DoMeleeAttack; Attack.DoAreaAttack; Projectile.OnHit
---

Every creature with an AI, bosses included, regenerates at a fixed share of its maximum health per second of world time.
The client that owns the creature heals it every 2 s for the world time since its last tick, read from the creature's
saved network object. That time keeps running while nobody is nearby, so a creature that comes back into range gets
it all at once. Sleeping counts too: it moves world time forward to the next morning over 12 s, and creatures heal
for the time skipped. A tamed creature doesn't regenerate while it is hungry. Heal numbers only show on tamed ones, so
a boss's health bar fills with no numbers shown. No creature attack in the game data heals the attacker on a hit
(`m_attackHealthReturnHit` and `m_healthReturn` are 0 everywhere).

- heal per second $= max health / T$, $T$ = `m_regenAllHPTime`, 3600 s unless listed below
- max health includes stars ([creature levels](mechanic:creature-levels)), so a starred creature heals faster and is full again in the same time
- sleep skips from bedtime to the next morning, 0.15 of a day in; bed is allowed from 0.5 of the day (afternoon), dusk
  is 0.85 (shares of the real day, which the sky's clock rescales)

{{sleep-skip}}

## Bosses

Health regenerated per second, and over one sleep from the earliest bedtime and from dusk.

{{regen-bosses}}

## Other creatures

Creatures that don't take an hour to regenerate.

{{regen-other}}
