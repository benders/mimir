---
title: Comfort and rest
summary: Comfort level, Resting, how long Rested lasts.
order: 9
sources: SE_Rested.CalculateComfortLevel; SE_Rested.UpdateTTL; SE_Rested.Setup; SE_Cozy.UpdateStatusEffect; Player.UpdateBaseValue; Player.UpdateEnvStatusEffects; Player.SetSleeping; Piece.GetComfort; Piece.GetAllComfortPiecesInRadius
---

Comfort is 1 outside shelter. In shelter it is 2 plus the comfort pieces within 10 m: only the best piece of each
comfort group counts, and a piece without a group counts once per kind. It is recomputed every 2 s. Resting needs a
fire's heat and sitting or shelter, and no enemy sensing the player, no burning, cold or freezing, and no Wet (unless
in a warm, cozy area). After 20 s of [Resting](effect:Resting) the player becomes [Rested](effect:Rested), renewed
while the rest goes on; waking from sleep also gives Rested. A renewal only replaces the timer when it is longer than
what is left.

- comfort $= 2 + Σ_{groups} best + Σ_{ungrouped} c$ in shelter, else 1
- Rested lasts $480 + 60 × (comfort - 1)$ s
- Rested: health regen × 1.5, stamina and eitr regen × 2, [skill gain](mechanic:skills) + 50%; Resting: health × 3, stamina and eitr × 4

## Most comfort by stage

{{max-comfort}}

## Comfort pieces

{{comfort-pieces}}
