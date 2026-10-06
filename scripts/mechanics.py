"""Support for the site's Mechanics section (site/mechanics/*.md). Stdlib only, imported by build-site.py.

Three parts:

1. A small Markdown renderer (`render`) for the subset the pages use: front matter, headings, paragraphs, bullet and
   numbered lists, pipe tables, fenced code, blockquotes, links, `code`, **bold**, *italic*, $formulas$.
   Block directives, alone on a line, embed generated content:  {{name}}  or  {{name arg}}
   (`chart armor`, `shields`, ...). They are looked up in the `blocks` mapping the caller passes in; an unknown
   directive is an error, so a typo fails the build. Link targets may be `kind:id` (item:ShieldWood,
   creature:Troll, piece:..., effect:...) or `mechanic:page`, resolved by the caller's `resolve`.
   The directive `{{calculator NAME}}` is the hook for interactive calculators, see `calculator_block`.

2. The mechanics as plain functions (`armor_through`, `block_power`, `block_outcome`, `star_multipliers`,
   `upgrade_cost_multiplier`, `pseudo_gap_max`). Each cites the decompiled method it mirrors. Pages and charts
   compute from these, and tests/test_mechanics.py checks them against hand-worked values from the code.

3. Inline-SVG line charts (`line_chart` and the three page charts). Colours come from the site's CSS custom
   properties (classes in site/style.css), so charts follow the light and dark themes. No scripts, no assets.
"""
import html
import math
import re
from pathlib import Path

esc = html.escape


# --- the mechanics --------------------------------------------------------------------------

def armor_through(dmg: float, ac: float) -> float:
    """Damage left after armor `ac` (also used for block power): HitData.DamageTypes.ApplyArmor(float, float).
    Armor <= 0 does nothing (the instance method returns early)."""
    if ac <= 0 or dmg <= 0:
        return dmg
    if ac < dmg / 2:
        return dmg - ac
    return min(1.0, max(0.0, dmg / (ac * 4))) * dmg  # dmg^2 / (4 ac)


def block_power(base: float, per_level: float, quality: int, skill: float, parry: float = 1.0) -> float:
    """Humanoid.BlockAttack with ItemDrop.ItemData.GetBlockPower: (base + (q-1) * perLevel) * (1 + 0.5 * skillFactor),
    skillFactor = clamp01(floor(skill) / 100) (Skills.GetSkillFactor); a parry multiplies by the shield's timedBlockBonus."""
    factor = min(1.0, max(0.0, math.floor(skill) / 100))
    b = base + max(0, quality - 1) * per_level
    return (b + b * factor * 0.5) * parry


def block_outcome(dmg: float, power: float) -> dict:
    """Blockable damage `dmg` against block power `power` (Humanoid.BlockAttack): what gets through, what is blocked, and
    the fraction of Humanoid.m_blockStaminaDrain that is spent (clamp01(blocked / power))."""
    through = armor_through(dmg, power)
    blocked = dmg - through
    return {"through": through, "blocked": blocked,
            "stamina_fraction": min(1.0, max(0.0, blocked / power)) if power > 0 else 0.0}


def star_multipliers(stars: int) -> dict:
    """Creature level = stars + 1. Health: Character.SetupMaxHealth (base * level). Damage: Attack.GetLevelDamageFactor
    (1 + 0.5 * (level - 1)). Level-multiplied drops: CharacterDrop.GenerateDropList (max(1, int(2^(level - 1))))."""
    level = stars + 1
    return {"health": level, "damage": 1 + max(0, level - 1) * 0.5, "drops": max(1, int(2 ** (level - 1)))}


def level_distribution(chance_percent: float, min_level: int, max_level: int) -> dict[int, float]:
    """Odds of each level a spawner produces (SpawnSystem.Spawn, SpawnArea.SpawnOne, CreatureSpawner.Spawn): start at
    min_level and, while below max_level, move up one level with probability chance_percent/100. Stars = level - 1."""
    c = chance_percent / 100
    out, alive = {}, 1.0
    for level in range(min_level, max_level):
        out[level] = alive * (1 - c)
        alive *= c
    out[max(min_level, max_level)] = alive
    return out


def upgrade_cost_multiplier(quality: int) -> float:
    """Times `amountPerLevel` that quality `quality` costs: Piece.Requirement.GetAmount (before floor)."""
    if quality <= 1:
        return 0.0
    return float(quality - 1) if quality < 4 else 4 + (quality - 4) / 2


MODIFIER_MULTIPLIER = {  # HitData.ApplyModifier; Ignore is handled before the switch and also gives 0
    "Normal": 1.0, "SlightlyResistant": 0.75, "Resistant": 0.5, "VeryResistant": 0.25, "Immune": 0.0, "Ignore": 0.0,
    "SlightlyWeak": 1.25, "Weak": 1.5, "VeryWeak": 2.0}


def should_override(a: str, b: str) -> bool:
    """HitData.DamageModifiers.ShouldOverride(a, b): does modifier `b` replace the current modifier `a`?
    Applied in order by DamageModifiers.Apply for the creature or player base, then armor pieces, then status effects."""
    resistant = ("Resistant", "VeryResistant", "SlightlyResistant", "Immune")
    if a == "Ignore":
        return False
    if b == "Immune":
        return True
    if a == "VeryResistant" and b == "Resistant":
        return False
    if a == "VeryWeak" and b == "Weak":
        return False
    if a in ("VeryResistant", "Resistant") and b == "SlightlyResistant":
        return False
    if a in ("VeryWeak", "Weak") and b == "SlightlyWeak":
        return False
    if a in resistant and b in ("Weak", "VeryWeak", "SlightlyWeak"):
        return False
    return True


def pseudo_gap_max(chance: float) -> int:
    """Most kills between two pseudo-random drops: after a drop the countdown is Random.Range(0, int(1/p*2 + 1)),
    decremented per kill, dropping at <= 0 (CharacterDrop.GenerateDropList), so the gap is max(1, countdown)."""
    return max(1, int(1 / chance * 2 + 1) - 1)


def pseudo_rate(chance: float) -> float:
    """Long-run drops per kill of the pseudo-random scheme: 1 / mean gap, gap = max(1, uniform 0..pseudo_gap_max)."""
    m = int(1 / chance * 2 + 1)  # Range(0, m): 0..m-1
    return m / (1 + sum(range(m)))  # gaps 1,1,2,...,m-1 over m outcomes


def curve(keys: list, t: float) -> float:
    """AnimationCurve.Evaluate on [time, value] keys, clamped at the ends. The dump has the keys but not their
    tangents, so between keys this is linear: an approximation of the game's curve."""
    if not keys:
        return 0.0
    if t <= keys[0][0]:
        return keys[0][1]
    for (t0, v0), (t1, v1) in zip(keys, keys[1:]):
        if t <= t1:
            return v0 + (v1 - v0) * (t - t0) / (t1 - t0)
    return keys[-1][1]


def adrenaline_gain(v: float, fill: float, gain_keys: list | None = None, rate: float = 1, modifier: float = 0) -> float:
    """Player.AddAdrenaline for v > 0 at fill fraction `fill` (adrenaline / max): × Game.m_adrenalineRate (world
    modifier), × m_adrenalineGainMultiplier(fill), then SEMan.ModifyAdrenaline adds that × each effect's
    m_adrenalineModifier (SE_Stats.ModifyAdrenaline)."""
    v *= rate * (curve(gain_keys, fill) if gain_keys else 1)
    return v * (1 + modifier)


def adrenaline_drain_time(max_a: float, start: float, degen_keys: list, steps: int = 1000) -> float:
    """Seconds for `start` adrenaline to drain to 0 once the delay has run out: Player.UpdateStats subtracts
    m_adrenalineDegen(adrenaline / max) per second, so t = ∫ dA / degen(A / max) (midpoint rule)."""
    h = start / steps
    return sum(h / curve(degen_keys, (k + 0.5) * h / max_a) for k in range(steps))


DAMAGE_TYPES = ("damage", "blunt", "slash", "pierce", "chop", "pickaxe", "fire", "frost", "lightning", "poison", "spirit")
TOOL_DAMAGE = frozenset({"chop", "pickaxe"})  # for trees and rocks; nearly every creature ignores them


def ignored_damage(creatures: list[dict]) -> dict[str, tuple[int, int]]:
    """Damage types more than half of the creatures are Immune to or Ignore (data/creatures.json damageModifiers),
    as {type: (count, total)}. DPS leaves them out."""
    out = {}
    for t in DAMAGE_TYPES:
        n = sum(1 for c in creatures if (c.get("damageModifiers") or {}).get(t) in ("Immune", "Ignore"))
        if creatures and n * 2 > len(creatures):
            out[t] = (n, len(creatures))
    return out


def hit_damage(damages: dict, skip=TOOL_DAMAGE) -> float:
    """One hit's damage against a creature at full skill roll: the weapon's damage types summed, less `skip`."""
    return sum(v for k, v in damages.items() if k in DAMAGE_TYPES and k not in skip)


def skill_roll(skill: float) -> tuple[float, float]:
    """Skills.GetRandomSkillFactor: each hit's damage × a uniform roll in [n - 0.15, n + 0.15] clamped to [0, 1],
    n = lerp(0.4, 1, skill / 100)."""
    n = 0.4 + 0.6 * skill / 100
    return max(0.0, n - 0.15), min(1.0, n + 0.15)


def combo_damage(per_hit: float, attack: dict) -> float:
    """Damage of one pass through the attack's chain (data/items.json `chain`): every hit × m_damageMultiplier
    (Attack.ModifyDamage), the last chain level's hits × the last-chain multiplier (Attack.DoMeleeAttack, DoAreaAttack)."""
    chain, mult, last = attack["chain"], attack.get("damageMultiplier") or 1, attack.get("lastChainMultiplier") or 1
    return sum(c["hits"] * per_hit * mult * (last if k == len(chain) - 1 else 1) for k, c in enumerate(chain))


def draw_time(draw_min: float, skill: float) -> float:
    """Humanoid.GetAttackDrawPercentage: a full draw takes lerp(m_drawDurationMin, 0.2 × it, skill / 100)."""
    return draw_min * (1 - 0.8 * skill / 100)


def reload_time(reload: float, skill: float) -> float:
    """ItemData.GetWeaponLoadingTime: lerp(m_reloadTime, 0.5 × it, skill / 100)."""
    return reload * (1 - 0.5 * skill / 100)


def attack_cycle(attack: dict | None, skill: float = 0) -> float | None:
    """Seconds between attacks held back to back (data/items.json attack timing).
    Melee and plain attacks: `cycle`. Bows (Player.UpdateAttackBowDraw): the next draw starts at release and the shot
    needs both a full draw and the end of the release animation (Humanoid.StartAttack refuses while InAttack), so
    max(draw, release). Crossbows: firing unloads (Attack.OnAttackTrigger); the reload runs once the attack ends and
    m_blockReloadTime has passed (Player.UpdateActionQueue, QueueReloadAction), then Attack.Start waits out the
    "reload done" minor action."""
    if not attack or not attack.get("chain") or attack.get("thrown") or attack.get("random"):
        return None
    if attack.get("cycle"):
        return attack["cycle"]
    anim = sum(c["time"] for c in attack["chain"])
    if attack.get("draw"):
        return max(draw_time(attack["draw"], skill), anim)
    if attack.get("reload") and attack.get("reloadDone") is not None:
        return max(anim, attack.get("reloadBlock", 0)) + reload_time(attack["reload"], skill) + attack["reloadDone"]
    return None


def dps(per_hit: float, attack: dict | None, skill: float = 0) -> float | None:
    """Damage per second holding the attack, every hit connecting: combo damage / attack_cycle. Skill only changes
    bow draw and crossbow reload. None when the cycle isn't known (projectile bursts, loops, thrown)."""
    cycle = attack_cycle(attack, skill)
    if not cycle or not per_hit:
        return None
    return combo_damage(per_hit, attack) / cycle


def food_fraction(left: float, burn: float) -> float:
    """Share of a food's health/stamina/eitr still given with `left` of its `burn` seconds to go
    (Player.UpdateFood: Pow(Clamp01(m_time / m_foodBurnTime), 0.3), recomputed once per second)."""
    return max(0.0, min(1.0, left / burn)) ** 0.3 if burn > 0 else 0.0


def food_can_eat_again(left: float, burn: float) -> bool:
    """The same food can be eaten again, or replaced when all three slots are full, once less than half its time is
    left (Player.Food.CanEatAgain)."""
    return left < burn / 2


def comfort_level(pieces: list[tuple[str, int, str | None]], shelter: bool = True) -> int:
    """Comfort from the comfort pieces within 10 m: (name, comfort, group or None). 1 outside shelter; in shelter
    1 + 1 + the best piece of each group + each distinct ungrouped name (SE_Rested.CalculateComfortLevel: sorted by
    group, then comfort descending, then name; a piece is skipped when it shares the previous one's group or name)."""
    if not shelter:
        return 1
    order = sorted(pieces, key=lambda x: x[0], reverse=True)
    order.sort(key=lambda x: (x[2] or "", -x[1]))
    level, prev = 2, None
    for p in order:
        if prev and ((p[2] and p[2] == prev[2]) or p[0] == prev[0]):
            prev = p
            continue
        level += p[1]
        prev = p
    return level


def rested_time(comfort: int, base_ttl: float, per_comfort: float) -> float:
    """Rested duration in seconds (SE_Rested.UpdateTTL: m_baseTTL + (comfort - 1) × m_TTLPerComfortLevel); a renewal only
    replaces the timer when it is longer than what is left."""
    return base_ttl + (comfort - 1) * per_comfort


def skill_requirement(level: float) -> float:
    """Experience to go from `level` to the next (Skills.Skill.GetNextLevelRequirement: Floor(level + 1)^1.5 × 0.5 + 0.5)."""
    return math.floor(level + 1) ** 1.5 * 0.5 + 0.5


def skill_raises(target: int, step: float, factor: float = 1.0, start: int = 0) -> int:
    """Raises of size step × factor to go from level `start` to `target` (Skills.Skill.Raise: the accumulator gains
    m_increseStep × factor per raise and resets to 0 at a level-up, so the overshoot is lost)."""
    gain = step * factor
    return sum(math.ceil(skill_requirement(lv) / gain - 1e-9) for lv in range(start, min(target, 100)))


def skill_after_deaths(level: float, deaths: int, factor: float) -> float:
    """Skill level after `deaths` deaths, each losing `factor` of the level (Skills.LowerAllSkills; also resets the
    progress towards the next level)."""
    return level * (1 - factor) ** deaths


# --- markdown -------------------------------------------------------------------------------

def parse_front_matter(text: str) -> tuple[dict, str]:
    """`---` / key: value lines / `---` at the top. Values are plain strings."""
    if not text.startswith("---\n"):
        return {}, text
    head, _, body = text[4:].partition("\n---\n")
    meta = {}
    for line in head.splitlines():
        if line.strip() and ":" in line:
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip()
    return meta, body


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", re.sub(r"<[^>]+>", "", text).lower()).strip("-")


class Ctx:
    """What the renderer needs from the site: link resolution and directive blocks. Defaults suit tests."""

    def __init__(self, resolve=None, blocks=None):
        self.resolve = resolve or (lambda scheme, id_: None)
        self.blocks = blocks or {}
        self.scripts: list[str] = []  # calculator scripts the rendered page needs (site-relative paths)


def formula(f: str) -> str:
    """Escaped formula text with superscripts: x^{a + b} and x^2 become <sup>."""
    f = esc(f, quote=False)
    f = re.sub(r"\^\{([^}]*)\}", r"<sup>\1</sup>", f)
    return re.sub(r"\^([\w.]+)", r"<sup>\1</sup>", f)


def inline(s: str, ctx: Ctx) -> str:
    stash: list[str] = []

    def keep(h: str) -> str:
        stash.append(h)
        return f"\x00{len(stash) - 1}\x00"

    s = re.sub(r"`([^`]+)`", lambda m: keep(f"<code>{esc(m.group(1), quote=False)}</code>"), s)
    s = re.sub(r"\$([^$]+)\$", lambda m: keep(f'<span class="formula">{formula(m.group(1))}</span>'), s)

    def link(m):
        text, url = m.group(1), m.group(2).strip()
        scheme, _, rest = url.partition(":")
        if rest and scheme in ("item", "creature", "piece", "effect", "mechanic"):
            target = ctx.resolve(scheme, rest)
            if target is None:
                raise ValueError(f"unresolved link: {url}")
            url = target
        return keep(f'<a href="{esc(url)}">{inline_text(text)}</a>')

    def inline_text(t: str) -> str:
        t = esc(t, quote=False)
        t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
        return re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", t)

    s = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", link, s)
    s = inline_text(s)
    return re.sub(r"\x00(\d+)\x00", lambda m: stash[int(m.group(1))], s)


def _cells(row: str) -> list[str]:
    row = row.strip()
    if row.startswith("|"):
        row = row[1:]
    if row.endswith("|"):
        row = row[:-1]
    return [c.strip() for c in re.split(r"(?<!\\)\|", row)]


def render(text: str, ctx: Ctx) -> str:
    """Markdown subset -> HTML (front matter must be removed first, see parse_front_matter)."""
    lines = text.splitlines()
    out: list[str] = []
    i = 0
    para: list[str] = []

    def flush():
        if para:
            out.append(f"<p>{inline(' '.join(para), ctx)}</p>")
            para.clear()

    while i < len(lines):
        line = lines[i]
        if not line.strip():
            flush()
            i += 1
        elif line.startswith("```"):
            flush()
            i += 1
            code = []
            while i < len(lines) and not lines[i].startswith("```"):
                code.append(lines[i])
                i += 1
            i += 1
            out.append(f"<pre><code>{esc(chr(10).join(code), quote=False)}</code></pre>")
        elif m := re.match(r"(#{1,3}) +(.+)", line):
            flush()
            n = len(m.group(1))
            out.append(f'<h{n} id="{slug(m.group(2))}">{inline(m.group(2), ctx)}</h{n}>')
            i += 1
        elif m := re.fullmatch(r"\{\{\s*(\S+?)(?:\s+(.+?))?\s*\}\}", line.strip()):
            flush()
            name, arg = m.group(1), m.group(2)
            if name == "calculator":
                out.append(calculator_block(arg or "", ctx))
            elif name in ctx.blocks:
                out.append(ctx.blocks[name](arg) if arg is not None else ctx.blocks[name]())
            else:
                raise ValueError(f"unknown directive: {line.strip()}")
            i += 1
        elif line.lstrip().startswith("|") and i + 1 < len(lines) and re.fullmatch(r"\s*\|?[\s:|-]+\|[\s:|-]*", lines[i + 1]):
            flush()
            head = _cells(line)
            aligns = [c.strip().endswith(":") for c in _cells(lines[i + 1])]
            i += 2
            rows = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                rows.append(_cells(lines[i]))
                i += 1
            cls = ' class="num"' if any(aligns) else ""
            th = "".join(f"<th>{inline(c, ctx)}</th>" for c in head)
            tr = "".join("<tr>" + "".join(f"<td>{inline(c, ctx)}</td>" for c in r) + "</tr>" for r in rows)
            out.append(f'<div class="tw"><table{cls}><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table></div>')
        elif re.match(r"(?:[-*]|\d+\.) +", line):
            flush()
            ordered = line[0].isdigit()
            items: list[list[str]] = []
            while i < len(lines) and lines[i].strip():
                if m := re.match(r"(?:[-*]|\d+\.) +(.*)", lines[i]):
                    items.append([m.group(1)])
                elif lines[i].startswith("  ") and items:
                    items[-1].append(lines[i].strip())
                else:
                    break
                i += 1
            tag = "ol" if ordered else "ul"
            out.append(f"<{tag}>" + "".join(f"<li>{inline(' '.join(x), ctx)}</li>" for x in items) + f"</{tag}>")
        elif line.startswith(">"):
            flush()
            quote = []
            while i < len(lines) and lines[i].startswith(">"):
                quote.append(lines[i][1:].strip())
                i += 1
            body = " ".join(quote)
            cls = ' class="inferred"' if body.lower().startswith("inferred") else ""
            out.append(f"<blockquote{cls}><p>{inline(body, ctx)}</p></blockquote>")
        else:
            para.append(line.strip())
            i += 1
    flush()
    return "\n".join(out)


def calculator_block(name: str, ctx: Ctx, static_dir: Path | None = None) -> str:
    """Hook for interactive calculators (none exist yet). `{{calculator NAME}}` renders a mount point,
    <div class="calc" data-calc="NAME">, and the page loads site/calc/NAME.js (plain JS, like site/search.js) if that file
    exists; the script finds its mount point with document.querySelector('[data-calc="NAME"]'). Without the script
    the block renders nothing, so a page may carry the directive before the calculator is written."""
    static_dir = static_dir or Path(__file__).resolve().parent.parent / "site" / "calc"
    if not re.fullmatch(r"[a-z0-9-]+", name) or not (static_dir / f"{name}.js").is_file():
        return ""
    ctx.scripts.append(f"calc/{name}.js")
    return f'<div class="calc" data-calc="{name}"><noscript><p class="note">This calculator needs JavaScript.</p></noscript></div>'


# --- charts ---------------------------------------------------------------------------------

def _fmt(v: float) -> str:
    return f"{v:.1f}".rstrip("0").rstrip(".")


def line_chart(series: list[dict], *, xlim, ylim, xticks, yticks, xlabel: str, ylabel: str, title: str, desc: str,
               ysuffix: str = "", W: int = 440, H: int = 290) -> str:
    """One inline SVG, thin lines, direct labels at the right end of each line.
    series: {"label", "points": [(x, y), ...], "marks": [(x, y), ...]}; series i is styled by class s{i+1}."""
    left, right, top, bottom = 46, 98, 12, 44
    pw, ph = W - left - right, H - top - bottom

    def px(x):
        return left + (x - xlim[0]) / (xlim[1] - xlim[0]) * pw

    def py(y):
        return top + ph - (y - ylim[0]) / (ylim[1] - ylim[0]) * ph

    uid = "c" + slug(title)[:24]
    g = [f'<svg class="chart" viewBox="0 0 {W} {H}" role="img" aria-labelledby="{uid}-t {uid}-d" '
         f'xmlns="http://www.w3.org/2000/svg">',
         f'<title id="{uid}-t">{esc(title)}</title><desc id="{uid}-d">{esc(desc)}</desc>']
    for y in yticks:
        g.append(f'<line class="grid" x1="{left}" x2="{left + pw}" y1="{py(y):.1f}" y2="{py(y):.1f}"/>')
        g.append(f'<text class="ax" x="{left - 6}" y="{py(y) + 4:.1f}" text-anchor="end">{_fmt(y)}{ysuffix}</text>')
    for x in xticks:
        g.append(f'<text class="ax" x="{px(x):.1f}" y="{top + ph + 16}" text-anchor="middle">{_fmt(x)}</text>')
    g.append(f'<line class="axis" x1="{left}" x2="{left + pw}" y1="{top + ph}" y2="{top + ph}"/>')
    g.append(f'<text class="axt" x="{left + pw / 2:.1f}" y="{H - 6}" text-anchor="middle">{esc(xlabel)}</text>')
    g.append(f'<text class="axt" transform="translate(11 {top + ph / 2:.1f}) rotate(-90)" text-anchor="middle">'
             f'{esc(ylabel)}</text>')
    ends = []
    for n, s in enumerate(series, 1):
        pts = " ".join(f"{px(x):.1f},{py(y):.1f}" for x, y in s["points"])
        g.append(f'<polyline class="ln s{n}" points="{pts}"/>')
        for x, y in s.get("marks", []):
            g.append(f'<circle class="dot s{n}" cx="{px(x):.1f}" cy="{py(y):.1f}" r="3"/>')
        ends.append([py(s["points"][-1][1]), n, s["label"]])
    # direct labels, nudged apart so they never overlap
    ends.sort()
    for k in range(1, len(ends)):
        ends[k][0] = max(ends[k][0], ends[k - 1][0] + 15)
    for y, n, label in ends:
        g.append(f'<text class="lbl t{n}" x="{left + pw + 6}" y="{y + 4:.1f}">{esc(label)}</text>')
    g.append("</svg>")
    return "".join(g)


def figure(svg: str, caption: str) -> str:
    return f'<figure class="chartfig">{svg}<figcaption>{esc(caption)}</figcaption></figure>'


ARMOR_HITS = (30, 60, 120)
BLOCK_HITS = (50, 100, 200)


def armor_chart() -> str:
    """Share of a hit that is taken vs armor, for three hit sizes: the piecewise armor formula."""
    series = []
    for d in ARMOR_HITS:
        series.append({"label": f"{d} hit", "points": [(a, armor_through(d, a) / d * 100) for a in range(0, 201)],
                       "marks": [(d / 2, 50)]})
    a60 = [armor_through(60, a) / 60 * 100 for a in (30, 60, 120)]
    desc = (f"Percent of damage taken against armor 0 to 200 for hits of {', '.join(map(str, ARMOR_HITS))}. "
            f"A 60 hit takes {_fmt(a60[0])}% at armor 30, {_fmt(a60[1])}% at armor 60 and {_fmt(a60[2])}% at armor 120.")
    return figure(line_chart(series, xlim=(0, 200), ylim=(0, 100), xticks=range(0, 201, 50), yticks=range(0, 101, 25),
                             xlabel="Armor", ylabel="Damage taken (% of the hit)", ysuffix="%",
                             title="Damage taken against armor", desc=desc),
                  "Dots: armor = D/2, where the formula switches from D − A to D²/4A.")


def block_chart() -> str:
    """Damage that gets through a block vs block power, for three hit sizes. Same formula as armor."""
    series = []
    for d in BLOCK_HITS:
        series.append({"label": f"{d} hit", "points": [(b, armor_through(d, b)) for b in range(0, 201)],
                       "marks": [(d / 2, d / 2)]})
    t = armor_through(100, 40), armor_through(100, 100)
    desc = (f"Damage that gets through a block against block power 0 to 200, for hits of "
            f"{', '.join(map(str, BLOCK_HITS))}. A 100 hit leaves {_fmt(t[0])} against block power 40 and {_fmt(t[1])} "
            f"against block power 100.")
    return figure(line_chart(series, xlim=(0, 200), ylim=(0, 200), xticks=range(0, 201, 50), yticks=range(0, 201, 50),
                             xlabel="Block power", ylabel="Damage through the block",
                             title="Damage through a block", desc=desc),
                  "Dots: B = D/2, where the formula switches from D − B to D²/4B.")


def stars_chart() -> str:
    """Health, damage and level-multiplied drop multipliers for 0 to 4 stars."""
    stars = range(0, 5)
    names = [("health", "Health"), ("damage", "Damage"), ("drops", "Drops")]
    series = [{"label": label, "points": [(s, star_multipliers(s)[k]) for s in stars],
               "marks": [(s, star_multipliers(s)[k]) for s in stars]} for k, label in names]
    m2 = star_multipliers(2)
    desc = (f"Multipliers by star count, 0 to 4. At 2 stars: health ×{m2['health']}, damage ×{_fmt(m2['damage'])}, "
            f"level-multiplied drops ×{m2['drops']}. Drops double with every star while health and damage grow in "
            f"fixed steps.")
    return figure(line_chart(series, xlim=(0, 4), ylim=(0, 16), xticks=range(0, 5), yticks=range(0, 17, 4),
                             xlabel="Stars", ylabel="Multiplier (×)", title="Multipliers by star level", desc=desc),
                  "Health ×level, damage ×(1 + 0.5·stars), level-multiplied drops ×2^stars.")


STAMINA_POWERS = (40, 80, 120)


def stamina_chart() -> str:
    """Stamina spent on a block vs blockable damage, for three block powers (player: m_blockStaminaDrain 10)."""
    series = [{"label": f"B {b}", "points": [(d, 10 * block_outcome(d, b)["stamina_fraction"]) for d in range(0, 301, 2)],
               "marks": [(2 * b, 10)]} for b in STAMINA_POWERS]
    desc = ("Stamina spent on a block against blockable damage 0 to 300, for block power "
            f"{', '.join(map(str, STAMINA_POWERS))}. It reaches the full 10 at damage = 2 × block power.")
    return figure(line_chart(series, xlim=(0, 300), ylim=(0, 10), xticks=range(0, 301, 100), yticks=range(0, 11, 2),
                             xlabel="Blockable damage", ylabel="Stamina", title="Block stamina cost", desc=desc),
                  "Dots: D = 2B, from where every block costs the full 10.")


def pseudo_chart() -> str:
    """Long-run drop rate of the pseudo-random countdown vs the nominal chance, 1 to 30%."""
    ps = [x / 1000 for x in range(10, 301, 2)]
    series = [{"label": "nominal", "points": [(p * 100, p * 100) for p in ps]},
              {"label": "actual", "points": [(p * 100, pseudo_rate(p) * 100) for p in ps]}]
    desc = (f"Long-run drop rate of the pseudo-random countdown against the nominal chance, 1% to 30%. "
            f"25% gives {_fmt(pseudo_rate(0.25) * 100)}%, 10% gives {_fmt(pseudo_rate(0.1) * 100)}%.")
    return figure(line_chart(series, xlim=(0, 30), ylim=(0, 30), xticks=range(0, 31, 10), yticks=range(0, 31, 10),
                             xlabel="Chance p (%)", ylabel="Drops per kill (%)", ysuffix="%",
                             title="Pseudo-random drop rate", desc=desc),
                  "The countdown keeps the rate near p; the integer cut-off moves it slightly.")


def upgrade_chart() -> str:
    """Upgrade cost multiplier (× amountPerLevel) by quality."""
    qs = range(2, 11)
    series = [{"label": "× perLevel", "points": [(q, upgrade_cost_multiplier(q)) for q in qs],
               "marks": [(q, upgrade_cost_multiplier(q)) for q in qs]}]
    desc = "Resource multiplier (times amountPerLevel) to reach quality 2 to 10: 1, 2, then 4 at quality 4 and +0.5 per level."
    return figure(line_chart(series, xlim=(2, 10), ylim=(0, 8), xticks=range(2, 11), yticks=range(0, 9, 2),
                             xlabel="Quality", ylabel="× amountPerLevel", title="Upgrade cost by quality", desc=desc),
                  "q − 1 below 4, then 4 + (q − 4)/2: the step to quality 4 doubles the cost.")


def adrenaline_chart(adr: dict) -> str:
    """Decay per second and the delay before decay starts, against how full the bar is (Player.UpdateStats,
    Player.AddAdrenaline); keys from the Player prefab, linear between them."""
    fills = [x / 100 for x in range(0, 101)]
    series = [{"label": "delay (s)", "points": [(f * 100, curve(adr["degenDelay"], f)) for f in fills],
               "marks": [(t * 100, v) for t, v in adr["degenDelay"]]},
              {"label": "decay (/s)", "points": [(f * 100, curve(adr["degen"], f)) for f in fills],
               "marks": [(t * 100, v) for t, v in adr["degen"]]}]
    top = max(v for s in series for _, v in s["points"])
    ymax = max(2, math.ceil(top / 2) * 2)
    d, dl = adr["degen"], adr["degenDelay"]
    desc = (f"Adrenaline decay per second and the delay after a gain before decay starts, by fill 0 to 100%. "
            f"Decay goes from {_fmt(d[0][1])} to {_fmt(d[-1][1])} per second; the delay from {_fmt(dl[0][1])} s to "
            f"{_fmt(dl[-1][1])} s.")
    return figure(line_chart(series, xlim=(0, 100), ylim=(0, ymax), xticks=range(0, 101, 25),
                             yticks=range(0, ymax + 1, 2), xlabel="Fill (% of max adrenaline)", ylabel="Seconds / per second",
                             title="Adrenaline decay", desc=desc),
                  "Dots: the curve keys in the Player prefab; linear between them (the dump has no tangents).")


def food_chart() -> str:
    """Share of a food's values left against the share of its time gone (Player.UpdateFood)."""
    xs = range(0, 101)
    series = [{"label": "value", "points": [(x, food_fraction(100 - x, 100) * 100) for x in xs],
               "marks": [(50, food_fraction(50, 100) * 100)]}]
    q = [food_fraction(100 - x, 100) * 100 for x in (50, 75, 90)]
    desc = (f"Share of a food's health, stamina and eitr still given, against the share of its duration gone. "
            f"Half way it still gives {_fmt(q[0])}%, at 75% {_fmt(q[1])}%, at 90% {_fmt(q[2])}%, then it drops to 0.")
    return figure(line_chart(series, xlim=(0, 100), ylim=(0, 100), xticks=range(0, 101, 25), yticks=range(0, 101, 25),
                             xlabel="Time gone (% of duration)", ylabel="Value (% of full)", ysuffix="%",
                             title="Food value over time", desc=desc),
                  "Dot: half the time gone, from where the food can be eaten again.")


def skills_chart() -> str:
    """Raises (uses) needed from level 0, for gain steps 1 and 0.5, without and with Rested (× 1.5)."""
    lv = range(0, 101, 2)
    series = [{"label": label, "points": [(L, skill_raises(L, step, factor) / 1000) for L in lv]}
              for label, step, factor in (("step 0.5", 0.5, 1), ("step 1", 1, 1), ("step 1, rested", 1, 1.5))]
    r = skill_raises(100, 1), skill_raises(50, 1)
    desc = (f"Raises needed to reach a level from 0, in thousands. With a gain step of 1: {r[1]:,} to level 50, "
            f"{r[0]:,} to 100. Step 0.5 needs about twice as many; Rested (× 1.5) about two thirds.")
    return figure(line_chart(series, xlim=(0, 100), ylim=(0, 45), xticks=range(0, 101, 25), yticks=range(0, 46, 15),
                             xlabel="Skill level", ylabel="Raises from 0 (thousands)", title="Skill experience", desc=desc),
                  "Each level needs ⌊L + 1⌋^1.5 × 0.5 + 0.5; leftover experience is lost at every level-up.")


CHARTS = {"armor": armor_chart, "block": block_chart, "stars": stars_chart, "stamina": stamina_chart,
          "pseudo": pseudo_chart, "upgrade": upgrade_chart, "food": food_chart, "skills": skills_chart}


FORGE_DURATION = 8  # InventoryGui.m_upgraderDuration (code default; the GUI isn't in the dump)
FORGE_DURATION_PER_LEVEL = 1  # InventoryGui.m_upgraderDurationPerLevel


def refine_odds(chance: float, break_chance: float) -> dict:
    """Outcome of one Forge of Potential attempt (InventoryGui.DoCrafting): a roll r in [0, 1) succeeds when
    r <= chance (+1 level), else breaks the item when break_chance >= 1 - r, else lowers it one level."""
    brk = max(0.0, 1 - max(chance, 1 - break_chance))
    return {"success": chance, "break": brk, "reduce": max(0.0, 1 - chance - brk)}


def refine_return(amount: int, per_level: int, level: int, fraction: float) -> int:
    """What a broken item gives back of one recoverable cost resource (InventoryGui.DoCrafting):
    ⌈(GetAmount(1) + GetAmount(level - 1)) × fraction⌉, level being the quality the attempt aimed for."""
    cost = lambda q: amount if q <= 1 else math.floor(upgrade_cost_multiplier(q) * per_level)
    return math.ceil((cost(1) + cost(level - 1)) * fraction)


def refine_time(level: int) -> float:
    """Seconds an attempt at the forge takes to reach `level` (InventoryGui.UpdateRecipe)."""
    return FORGE_DURATION + level * FORGE_DURATION_PER_LEVEL


def refine_streak(chance: float, steps: int) -> float:
    """Chance to gain `steps` levels in a row when every failure breaks the item."""
    return chance ** steps


def world_piece_drop(amount: int) -> int:
    """What breaking a piece a player didn't place gives of one of its cost items: a third, at least 1
    (Piece.DropResources: Mathf.Max(1, dropCount / 3) unless IsPlacedByPlayer)."""
    return max(1, amount // 3)


FACTIONS = ("Players", "AnimalsVeg", "ForestMonsters", "Undead", "Demon", "MountainMonsters", "SeaMonsters",
            "PlainsMonsters", "Boss", "MistlandsMonsters", "Dverger", "PlayerSpawned", "TrainingDummy", "DeepNorth")  # Character.Faction


def is_enemy(a: str, b: str) -> bool:
    """Whether a creature of faction `a` treats one of faction `b` as an enemy, both untamed and not aggravated and
    in different groups (BaseAI.IsEnemy(Character, Character), its faction switch). Not symmetric: animals treat
    everyone as an enemy (they flee), forest monsters ignore animals."""
    if a == b:
        return False
    if a in ("AnimalsVeg", "PlayerSpawned"):
        return True
    if a == "Players":
        return b != "Dverger"
    if a in ("ForestMonsters", "MistlandsMonsters", "DeepNorth"):
        return b not in ("AnimalsVeg", "Boss")
    if a == "Undead":
        return b not in ("Demon", "Boss")
    if a == "Demon":
        return b not in ("Undead", "Boss")
    if a in ("MountainMonsters", "SeaMonsters", "PlainsMonsters"):
        return b != "Boss"
    if a == "Dverger":
        return b not in ("AnimalsVeg", "Boss", "Players")
    if a == "Boss":
        return b in ("Players", "PlayerSpawned")
    if a == "TrainingDummy":
        return b == "Players"
    return False


RAID_BASE_VALUE = 3  # RandEventSystem.CheckBase: player.baseValue >= 3
RAID_BASE_RADIUS = 20  # Player.UpdateBaseValue: EffectArea.GetBaseValue(position, 20f)


def raid_roll(interval_min: float, chance: float, rate: float = 1) -> tuple[float, float]:
    """(minutes between rolls, chance per roll in %) for a random raid (RandEventSystem.UpdateRandomEvent): the timer
    runs to m_eventIntervalMin × 60 × eventRate seconds, then a raid starts with m_eventChance / eventRate %."""
    return interval_min * rate, min(100.0, chance / rate)


def raid_wait(interval_min: float, chance: float, rate: float = 1) -> float:
    """Expected minutes until a raid starts, while one is possible: rolls are independent, so interval / p."""
    every, p = raid_roll(interval_min, chance, rate)
    return every / (p / 100)
