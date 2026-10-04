---
title: Food
summary: Three slots, values that fade, max health, stamina and eitr, healing.
order: 8
sources: Humanoid.UseItem; Player.CanEat; Player.EatFood; Player.Food.CanEatAgain; Player.GetMostDepletedFood; Player.UpdateFood; Player.GetTotalFoodValue; Player.UpdateStats; Player.OnDeath
---

Three slots. A food already in a slot can be eaten again only once less than half its time is left, which refills it.
With all three slots full, a new food replaces the most depleted one past half its time; if none is, it can't be
eaten. Each food adds its health, stamina and eitr to the player's base, scaled down as its time runs out
(recomputed every second), and it ends at 0. Healing doesn't fade: every 10 s the player heals the sum of the foods'
healing values. Dying empties every slot.

- max health $= 25 + Σ health × f$; max stamina $= 50 + Σ stamina × f$; max eitr $= Σ eitr × f$
- $f = (t / T)^{0.3}$, $t$ = time left, $T$ = the food's duration
- heal every 10 s $= Σ regen × Π m$, $m$ = active effects' health regen multipliers ([Rested](effect:Rested) 1.5, [Resting](effect:Resting) 3, [Wet](effect:Wet) 0.75)
- eat again when $t < T / 2$; time runs × the world's food rate modifier (1 by default)
- only consumables are eaten: raw meat and fish have food values but are materials

{{chart food}}

## Foods

{{foods}}
