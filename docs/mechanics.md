# Game mechanics notes

Findings from reading the decompiled game code (`make decompile`, Valheim 1.0.16). Source material for the
site's mechanics pages. Re-check against the decompiled code after major game updates.

## Blocking (`Humanoid.BlockAttack`, `HitData`, `ItemDrop.ItemData.GetBlockPower`)

- Block power `B = (block + blockPerLevel × (quality − 1)) × (1 + 0.5 × skill/100)`. Skill is the floored
  Blocking level (status effects can modify it; none do for Blocking in vanilla), clamped to 0–100.
- Parry (`timedBlockBonus > 1`, within 0.25 s of raising the shield): `B ×= timedBlockBonus`. Tower shields
  have no bonus and can't parry.
- The shield's own damage modifiers apply to the hit first (Serpent Scale: pierce Resistant = ×0.5).
- Blockable damage `D` = blunt + slash + pierce + fire + frost + lightning + poison + spirit (+ nonPlayer).
- Damage that gets through uses the armor formula: `D²/(4B)` if `D ≤ 2B`, else `D − B`. Never zero.
- Stamina: `10 × clamp01((D − through)/B)`; a perfect parry costs the player's `m_perfectBlockStaminaDrain` (0).
- The damage that gets through adds to stagger; the player is staggered (guard broken, full hit taken) at
  `maxHP × 0.4`. Running out of stamina also fails the block.
- Durability loss per block: `useDurabilityDrain × D/B`.
- Parry force (knockback) depends only on shield level, not skill. Blocking XP: +1 per block, +2 per parry.

## Creature drops (`CharacterDrop.GenerateDropList`)

- Level multiplier `m = 2^(level − 1)` (1★ = level 2). `levelMultiplier` drops scale both chance and amount by m.
- Amount uses `Random.Range(min, max)` (int, max exclusive) at default resource rate.
- **Pseudo-random drops**: if effective chance `p ≤ 0.3` and the `NoPseudoDrops` global key is unset, a
  per-item countdown replaces the roll. First countdown is uniform in [0, 2/p − 1], after a drop it's uniform
  in [0, 2/p]; it decrements per kill and drops at ≤ 0. Same long-run rate, but at most 2/p kills between
  drops. The counter is a static dictionary keyed by item name and resets if the chance changes.
- Drops are rolled by the **owner** of the creature's ZDO (`CheckDeath` runs only when `IsOwner()`; damage
  RPCs are forwarded to the owner). On a dedicated server the server never owns creatures near players (its
  reference position is parked off-map in `Game.FixedUpdate`), so a **client** rolls the drop, and the
  counters are per client process (reset on relog).

## Creature attacks

- Damage scales by level: `1 + 0.5 × (level − 1)` (`Attack.cs`).
