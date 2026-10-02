#!/usr/bin/env python3
"""Build the static site from data/ and the extracted icons. Stdlib only.

    scripts/build-site.py [data_dir] [icons_dir] [out_dir]
        # default: data/ + .cache/dump/public/icons -> .cache/site/public

One page per item, creature, piece and status effect, plus index pages and a client-side search
index (search.json, used by site/search.js). Derived relations (crafted from, used in, dropped by,
crafted at) are computed here, not stored in data/. Every page sets <base href> to the site root,
so all links are root-relative and the site works from any sub-path or straight from disk.

Item stats per quality level follow the game's own formulas (assembly_valheim):
  ItemDrop.ItemData.GetDamage/GetArmor/GetMaxDurability/GetBaseBlockPower: base + (q-1) * perLevel
  Piece.Requirement.GetAmount(q):     q=1 amount; q=2,3 (q-1)*perLevel; q>=4 (4+(q-4)/2)*perLevel
  Recipe.GetRequiredStationLevel(q):  max(1, stationLevel) + q - 1
"""
import html
import json
import math
import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import quote, unquote

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data"
ICONS = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / ".cache/dump/public/icons"
OUT = Path(sys.argv[3]) if len(sys.argv) > 3 else ROOT / ".cache/site/public"
STATIC = ROOT / "site"


def load(name: str):
    return json.loads((DATA / f"{name}.json").read_text(encoding="utf-8"))


META = load("meta")
ITEMS = {i["id"]: i for i in load("items")}
CREATURES = {c["id"]: c for c in load("creatures")}
PIECES = {p["id"]: p for p in load("pieces")}
EFFECTS = {e["id"]: e for e in load("status_effects")}
RECIPES = load("recipes")
SPAWNS = load("spawns")
SOURCES = {s["id"]: s for s in load("sources")}
# normalize currently emits some conversions twice (#18)
PROCESSING = list({json.dumps(p, sort_keys=True): p for p in load("processing")}.values())
HAVE_ICONS = {p.stem for p in ICONS.glob("*.png")} if ICONS.is_dir() else set()

KINDS = {"item": "items", "creature": "creatures", "piece": "pieces", "effect": "effects"}
WEAPONS = {"OneHandedWeapon", "TwoHandedWeapon", "TwoHandedWeaponLeft", "Bow", "Torch"}
ARMOR = {"Helmet", "Chest", "Legs", "Shoulder"}
TYPE_LABELS = {  # index order
    "OneHandedWeapon": "One-handed weapons", "TwoHandedWeapon": "Two-handed weapons",
    "TwoHandedWeaponLeft": "Two-handed weapons (left)", "Bow": "Bows and crossbows", "Ammo": "Ammo",
    "AmmoNonEquipable": "Ammo (non-equipable)", "Shield": "Shields", "Helmet": "Helmets", "Chest": "Chest armor",
    "Legs": "Leg armor", "Shoulder": "Capes", "Utility": "Utility", "Trinket": "Trinkets", "Tool": "Tools",
    "Torch": "Torches", "Consumable": "Food and potions", "Fish": "Fish", "Material": "Materials",
    "Trophy": "Trophies", "Misc": "Miscellaneous", "Customization": "Customization",
}
PROCESS_LABELS = {"smelter": "Smelting", "cooking": "Cooking", "fermenter": "Fermenting"}

esc = html.escape
RICH_TEXT = re.compile(r"</?(?:color|b|i|size)\b[^>]*>", re.I)


def clean(s) -> str:
    """Display text: drop Unity rich-text tags (<color=orange>...)."""
    return RICH_TEXT.sub("", str(s or "")).strip()


def pretty_id(s: str) -> str:
    s = re.sub(r"^(piece_|SetEffect_|SE_|Potion_)", "", s)
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", s.replace("_", " "))
    return s.strip().capitalize() if s.islower() else s.strip()


def words(key: str) -> str:
    return re.sub(r"([a-z])([A-Z])", r"\1 \2", key).capitalize()


def num(v) -> str:
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float):
        v = round(v, 2)
        if v == int(v):
            v = int(v)
    return f"{v:,}" if isinstance(v, int) and abs(v) >= 10000 else str(v)


def duration(sec) -> str:
    if sec >= 60 and sec % 60 == 0:
        return f"{sec // 60:g} min" if isinstance(sec, int) else f"{sec / 60:g} min"
    return f"{num(sec)} s"


def pct(v) -> str:
    return f"{num(round(v * 100, 1))}%"


def rng(lo, hi) -> str:
    return num(lo) if lo == hi else f"{num(lo)}–{num(hi)}"


# --- entity registry and links --------------------------------------------------------------

def icon_of(kind: str, e: dict):
    """Creatures have no icon of their own; use their trophy's."""
    if kind == "creature":
        return next((ITEMS[d["item"]].get("icon") for d in e.get("drops", [])
                     if ITEMS.get(d["item"], {}).get("type") == "Trophy"), None)
    return e.get("icon")


def entity(kind: str, id_: str):
    return {"item": ITEMS, "creature": CREATURES, "piece": PIECES, "effect": EFFECTS}[kind].get(id_)


def has_page(kind: str, id_: str) -> bool:
    e = entity(kind, id_)
    return e is not None and not (kind == "item" and (e.get("internal") or e.get("enemyOnly"))) \
        and id_ not in MERGED[kind]


def original(item_id: str) -> str:
    """The player item an enemy-only copy imitates (FW_HelmetBronze -> HelmetBronze), else the id itself."""
    orig = item_id.split("_", 1)[-1]
    if ITEMS.get(item_id, {}).get("enemyOnly") and orig in ITEMS and ITEMS[orig].get("name") == ITEMS[item_id].get("name"):
        return orig
    return item_id


def base_name(kind: str, id_: str) -> str:
    e = entity(kind, id_)
    return clean(e.get("name")) if e and e.get("name") else pretty_id(id_)


def name_of(kind: str, id_: str) -> str:
    id_ = MERGED[kind].get(id_, id_)
    q = QUALIFIED[kind].get(id_)
    return f"{base_name(kind, id_)} ({q})" if q else base_name(kind, id_)


def href(kind: str, id_: str) -> str:
    return f"{KINDS[kind]}/{quote(id_)}.html"


def icon(name, cls="ico") -> str:
    if not name or name not in HAVE_ICONS:
        return f'<span class="{cls} noico"></span>'
    return f'<img class="{cls}" src="icons/{quote(name)}.png" alt="" loading="lazy">'


def link(kind: str, id_: str, qty=None) -> str:
    id_ = MERGED[kind].get(id_, id_)
    e = entity(kind, id_)
    q = f'<span class="qty">×{esc(str(qty))}</span>' if qty is not None else ""
    label = f'{icon(icon_of(kind, e) if e else None)}<span>{esc(name_of(kind, id_))}</span>{q}'
    if has_page(kind, id_):
        return f'<a class="ref" href="{href(kind, id_)}">{label}</a>'
    return f'<span class="ref">{label}</span>'


def source_name(s: dict) -> str:
    if s.get("name"):
        return clean(s["name"])
    parent = next((p for p in SOURCES.values() if p.get("becomes") == s["id"]), None)
    if parent:
        return f"{source_name(parent)} ({s['kind']})"
    return pretty_id(s["id"])


# --- derived relations ----------------------------------------------------------------------

crafted_by = defaultdict(list)       # item -> recipes producing it
used_in_recipe = defaultdict(list)   # item -> recipes consuming it
# --- variants: prefabs sharing a display name ------------------------------------------------
# Identical copies (Troll / Troll_sleeping, FishRaw / FishAnglerRaw) merge into one page; the rest get a qualifier
# derived from the words their ids don't share: "Skeleton (Swamp, no bow)", "Kall Fimbulbringer (phase 2)".

ID_WORDS = {"NoArcher": "noarcher", "NonSleeping": "nonsleeping", "DualWield": "dualwield", "DeepNorth": "deepnorth"}
QUALIFIERS = {  # id word -> label; "" drops the word
    "sleeping": "sleeping", "nonsleeping": "awake", "nochest": "raid", "ranged": "archer", "noarcher": "no bow",
    "deepnorth": "Deep North", "meadows": "Meadows", "mountains": "Mountain", "mountain": "Mountain",
    "swamps": "Swamp", "swamp": "Swamp", "ashlands": "Ashlands", "dualwield": "dual-wield", "p2": "phase 2",
    "p3": "phase 3", "fem": "female", "tenta": "",
}


def id_words(id_: str) -> list[str]:
    for k, v in ID_WORDS.items():
        id_ = id_.replace(k, f"_{v}_")
    return [w.lower() for part in id_.split("_") for w in re.findall(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])", part)]


def qualifier(id_: str, others: list[str], name: str) -> str:
    """Words of the id that the other ids (or the display name) don't have, as labels."""
    common = set.intersection(*(set(id_words(o)) for o in [id_, *others]))
    named = set(re.findall(r"[a-z0-9]+", name.lower()))
    labels = [QUALIFIERS.get(w, w) for w in id_words(id_) if w not in common and w not in named]
    return ", ".join(dict.fromkeys(x for x in labels if x))


def variants(kind: str, coll: dict, shown) -> tuple[dict, dict]:
    """(merged id -> page id, page id -> qualifier) for entities whose display names collide."""
    groups = defaultdict(list)
    for id_ in sorted(coll):
        if shown(id_):
            groups[base_name(kind, id_)].append(id_)
    merged, qualified = {}, {}
    for name, ids in groups.items():
        if len(ids) < 2:
            continue
        pages = []
        for id_ in sorted(ids, key=lambda x: (len(x), x)):  # the shortest id of identical copies keeps the page
            same = {k: v for k, v in coll[id_].items() if k != "id"}
            twin = next((p for p in pages if {k: v for k, v in coll[p].items() if k != "id"} == same), None)
            if twin:
                merged[id_] = twin
            else:
                pages.append(id_)
        for id_ in pages:
            q = qualifier(id_, [o for o in pages if o != id_], name) if len(pages) > 1 else ""
            if q:
                qualified[id_] = q
        labels = defaultdict(list)
        for id_ in pages:
            labels[qualified.get(id_, "")].append(id_)
        for ids_ in labels.values():  # still ambiguous: fall back to the id
            if len(ids_) > 1:
                for id_ in ids_:
                    qualified[id_] = pretty_id(id_)
    return merged, qualified


MERGED, QUALIFIED = {k: {} for k in KINDS}, {k: {} for k in KINDS}
MERGED["item"], QUALIFIED["item"] = variants(
    "item", ITEMS, lambda i: not (ITEMS[i].get("internal") or ITEMS[i].get("enemyOnly")))
MERGED["creature"], QUALIFIED["creature"] = variants("creature", CREATURES, lambda c: True)


def variant_note(kind: str, id_: str) -> str:
    """For an entry of a merged copy shown on its page: what sets the copy apart ("sleeping")."""
    page_id = MERGED[kind].get(id_)
    return qualifier(id_, [page_id], base_name(kind, id_)) or pretty_id(id_) if page_id else ""


used_in_piece = defaultdict(list)    # item -> pieces built with it
crafted_at = defaultdict(list)       # station piece -> recipes
built_at = defaultdict(list)         # station piece -> pieces needing it nearby
extensions = defaultdict(list)       # station piece -> extension pieces
process_from = defaultdict(list)     # item -> conversions consuming it (input or fuel)
process_to = defaultdict(list)       # item -> conversions producing it
process_at = defaultdict(list)       # station -> conversions
dropped_by = defaultdict(list)       # item -> (creature id, drop)
found_in = defaultdict(list)         # item -> (source, text)
effect_users = defaultdict(list)     # effect -> (item id, how)
spawns_of = defaultdict(list)        # creature -> spawn entries
tool_pieces = defaultdict(list)      # tool item -> pieces
set_members = defaultdict(list)      # set name -> items

for r in RECIPES:
    if r.get("item"):
        crafted_by[r["item"]].append(r)
    for res in r["resources"]:
        used_in_recipe[res["item"]].append(r)
    if r.get("station"):
        crafted_at[r["station"]].append(r)
for p in PIECES.values():
    for res in p.get("resources", []):
        used_in_piece[res["item"]].append(p)
    if p.get("station"):
        built_at[p["station"]].append(p)
    if p.get("extends"):
        extensions[p["extends"]].append(p)
    for t in p.get("tools", []):
        tool_pieces[t].append(p)
for c in PROCESSING:
    process_from[c["from"]].append(c)
    if c.get("fuel") and c["fuel"] != c["from"]:
        process_from[c["fuel"]].append(c)
    process_to[c["to"]].append(c)
    process_at[c["station"]].append(c)
for c in CREATURES.values():
    for d in c.get("drops", []):
        dropped_by[d["item"]].append((c["id"], d))
for s in SOURCES.values():
    if s.get("pickable"):
        pk = s["pickable"]
        found_in[pk["item"]].append((s, f"pick ×{num(pk.get('amount', 1))}"))
    dr = s.get("drops") or {}
    for it in dr.get("items", []):
        found_in[it["item"]].append((s, rng(it.get("min", 1), it.get("max", 1))))
for i in ITEMS.values():
    if i.get("internal") or i.get("enemyOnly"):
        continue
    if i.get("consumeEffect"):
        effect_users[i["consumeEffect"]].append((i["id"], "consumed"))
    if i.get("equipEffect"):
        effect_users[i["equipEffect"]].append((i["id"], "equipped"))
    if i.get("set"):
        set_members[i["set"]["name"]].append(i["id"])
        if i["set"].get("effect"):
            effect_users[i["set"]["effect"]].append((i["id"], f"set of {i['set']['size']}"))
for s in SPAWNS:
    spawns_of[s["creature"]].append(s)
for kind, rels in {"item": [crafted_by, used_in_recipe, used_in_piece, process_from, process_to, dropped_by,
                            found_in, tool_pieces],
                   "creature": [spawns_of]}.items():
    for variant, page_id in MERGED[kind].items():  # a merged copy's relations show on its page
        for rel in rels:
            if variant in rel:
                rel[page_id].extend(rel.pop(variant))

BIOMES = {  # game progression order (creatures index)
    "Meadows": "Meadows", "BlackForest": "Black Forest", "Swamp": "Swamp", "Mountain": "Mountain",
    "Plains": "Plains", "Mistlands": "Mistlands", "AshLands": "Ashlands", "DeepNorth": "Deep North", "Ocean": "Ocean",
}


def biome_weights(cid: str, seen: frozenset = frozenset()) -> dict[str, float]:
    """How strongly a creature belongs to each biome. Each world, location or dungeon spawn spreads one unit over
    its biomes, so a spawn limited to one biome outweighs a night spawn across five. Raids and spawns everywhere
    say nothing. Offspring and hatchlings inherit from their parents; raids are the last resort."""
    def spread(sources):
        w = defaultdict(float)
        for s in spawns_of[cid]:
            bs = [b for b in s.get("biomes", []) if b in BIOMES]
            if s.get("source", "world") in sources and 0 < len(bs) < len(BIOMES):
                for b in bs:
                    w[b] += 1 / len(bs)
        return w

    w = spread({"world", "location", "dungeon"})
    if not w:
        seen |= {cid}
        parents = [s["parent"] for s in spawns_of[cid] if s.get("source") == "offspring"]
        parents += [e["parent"] for s in spawns_of[cid] if s.get("source") == "egg"
                    for e in spawns_of[s["item"]] if e.get("source") == "offspring"]
        for p in parents:
            if p not in seen:
                for b, v in biome_weights(p, seen).items():
                    w[b] += v
    return w or spread({"raid"})


def creature_biomes(cid: str) -> list[str]:
    """Biomes in progression order."""
    w = biome_weights(cid)
    return [b for b in BIOMES if b in w]


def home_biome(cid: str) -> str | None:
    """The biome a creature is listed under: the strongest, the earliest on a tie."""
    w = biome_weights(cid)
    order = list(BIOMES)
    return max(w, key=lambda b: (round(w[b], 6), -order.index(b))) if w else None


# --- page shell -----------------------------------------------------------------------------

written: list[Path] = []


def page(path: str, title: str, body: str, kind_label: str = "") -> None:
    depth = path.count("/")
    base = "../" * depth or "./"
    doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<base href="{base}">
<title>{esc(title)} · Mimir</title>
<link rel="stylesheet" href="style.css">
<script src="search.js" defer></script>
</head>
<body>
<header class="top">
  <a class="brand" href="index.html">Mimir</a>
  <nav>{"".join(f'<a href="{d}/index.html">{d.capitalize()}</a>' for d in KINDS.values())}</nav>
  <div class="search"><input id="q" type="search" placeholder="Search…  ( / )" autocomplete="off" aria-label="Search">
  <ol id="results" hidden></ol></div>
</header>
<main>
{f'<p class="crumb">{kind_label}</p>' if kind_label else ""}{body}
</main>
<footer>Valheim {esc(META["gameVersion"])} · data extracted from the dedicated server ·
not affiliated with Iron Gate</footer>
</body>
</html>
"""
    out = OUT / path
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(doc, encoding="utf-8")
    written.append(out)


def section(title: str, content: str) -> str:
    return f"<section><h2>{esc(title)}</h2>{content}</section>" if content else ""


def kv(rows) -> str:
    rows = [(k, v) for k, v in rows if v not in (None, "", [])]
    if not rows:
        return ""
    return '<dl class="kv">' + "".join(f"<dt>{esc(k)}</dt><dd>{v}</dd>" for k, v in rows) + "</dl>"


def table(head, rows, cls="") -> str:
    if not rows:
        return ""
    th = "".join(f"<th>{h}</th>" for h in head)
    tr = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<div class="tw"><table class="{cls}"><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table></div>'


def reflist(links) -> str:
    links = list(dict.fromkeys(links))
    return '<ul class="refs">' + "".join(f"<li>{l}</li>" for l in links) + "</ul>" if links else ""


def header(e: dict, kind: str, subtitle: str, desc: str = "") -> str:
    d = f'<p class="desc">{esc(clean(desc))}</p>' if desc else ""
    return (f'<div class="hero">{icon(icon_of(kind, e), "big")}<div><h1>{esc(name_of(kind, e["id"]))}</h1>'
            f'<p class="sub">{subtitle}</p>{d}</div></div>')


def modifiers_table(mods: dict) -> str:
    if not mods:
        return ""
    return '<ul class="mods">' + "".join(
        f'<li class="m-{esc(v.lower())}"><span>{esc(k)}</span>{esc(words(v))}</li>' for k, v in mods.items()) + "</ul>"


def damages(d: dict) -> str:
    return ", ".join(f"{num(v)} {esc(k)}" for k, v in (d or {}).items())


# --- items ----------------------------------------------------------------------------------

def req_amount(res: dict, q: int) -> int:
    if q <= 1:
        return res.get("amount", 0)
    n = (q - 1) if q < 4 else 4 + (q - 4) / 2
    return math.floor(n * res.get("perLevel", 0) + (res.get("amount", 0) if res.get("upgrader") else 0))


def recipe_block(r: dict, max_q: int) -> str:
    station = link("piece", r["station"]) if r.get("station") else "by hand"
    base_lvl = max(1, r.get("stationLevel", 1))
    normal = [x for x in r["resources"] if not x.get("upgrader")]
    upgrader = [x for x in r["resources"] if x.get("upgrader")]
    out = f'<p>{station}{f" (level {base_lvl})" if r.get("station") else ""}'
    out += f' · makes ×{r["amount"]}</p>' if r["amount"] > 1 else "</p>"
    if r.get("anyOneIngredient"):
        out += "<p class=note>Needs any one of these ingredients.</p>"
    qs = range(1, max_q + 1) if not r.get("upgradeOnly") else range(2, max_q + 1)
    rows = []
    for q in qs:
        cost = [link("item", x["item"], req_amount(x, q)) for x in normal if req_amount(x, q) > 0]
        lvl = f"{base_lvl + q - 1}" if r.get("station") else ""
        rows.append([str(q), lvl, " ".join(cost)])
    if max_q > 1 or r.get("upgradeOnly"):
        out += table(["Quality", "Station level", "Cost (craft / upgrade)"], rows, "cost")
    elif rows:
        out += f'<p class="cost">{rows[0][2]}</p>'
    if upgrader:
        out += ('<p class=note>At the Upgrade Station: '
                + " ".join(link("item", x["item"], x.get("amount", 1)) for x in upgrader) + "</p>")
    return out


def quality_table(i: dict) -> str:
    t, mq = i["type"], i.get("maxQuality", 1)
    cols = []  # (label, base, perLevel)
    dmg, dpl = i.get("damages", {}), i.get("damagesPerLevel", {})
    for k in dict.fromkeys([*dmg, *dpl]):
        cols.append((k.capitalize(), dmg.get(k, 0), dpl.get(k, 0)))
    if t in ARMOR:
        cols.append(("Armor", i.get("armor", 0), i.get("armorPerLevel", 0)))
    if t in WEAPONS | {"Shield"} and i.get("block"):
        cols.append(("Block", i.get("block", 0), i.get("blockPerLevel", 0)))
    if i.get("parryForce"):
        cols.append(("Parry force", i["parryForce"], i.get("parryForcePerLevel", 0)))
    if i.get("durability"):
        cols.append(("Durability", i["durability"]["max"], i["durability"].get("perLevel", 0)))
    if not cols:
        return ""
    if mq <= 1:
        return kv((c[0], num(c[1])) for c in cols)
    rows = [[str(q)] + [num(b + (q - 1) * p) for _, b, p in cols] for q in range(1, mq + 1)]
    return table(["Quality"] + [esc(c[0]) for c in cols], rows, "num")


def attack_text(a: dict) -> str:
    parts = [esc(words(a.get("type", "")))]
    if a.get("stamina"):
        parts.append(f"{num(a['stamina'])} stamina")
    if a.get("eitr"):
        parts.append(f"{num(a['eitr'])} eitr")
    if a.get("damageMultiplier") and a["damageMultiplier"] != 1:
        parts.append(f"×{num(a['damageMultiplier'])} damage")
    if a.get("projectile"):
        parts.append(f"projectile {esc(pretty_id(a['projectile']))}")
    return ", ".join(p for p in parts if p)


def item_page(i: dict) -> None:
    t = i["type"]
    facts = [
        ("Weight", num(i["weight"])), ("Stack", num(i["stack"]) if i.get("stack", 1) > 1 else None),
        ("Value", f'{num(i["value"])} coins' if i.get("value") else None),
        ("Max quality", num(i["maxQuality"]) if i.get("maxQuality", 1) > 1 else None),
        ("Teleport", "no" if i.get("noTeleport") else None), ("DLC", esc(i["dlc"]) if i.get("dlc") else None),
    ]
    combat = []
    if t in WEAPONS | {"Shield", "Tool", "Ammo", "AmmoNonEquipable"}:
        if t != "Tool":
            combat.append(("Skill", esc(words(i["skill"])) if i.get("skill") else None))
        if i.get("attack"):
            combat.append(("Primary attack", attack_text(i["attack"])))
        if i.get("secondaryAttack"):
            combat.append(("Secondary attack", attack_text(i["secondaryAttack"])))
        if t in WEAPONS | {"Ammo", "AmmoNonEquipable"}:
            combat += [("Knockback", num(i["attackForce"]) if i.get("attackForce") else None),
                       ("Backstab", f'×{num(i["backstab"])}' if i.get("backstab") else None)]
        if t in WEAPONS | {"Shield"}:
            combat.append(("Parry bonus", f'×{num(i["parryBonus"])}' if i.get("parryBonus") else None))
        if {"chop", "pickaxe"} & set(i.get("damages", {})):
            combat.append(("Tool tier", num(i.get("toolTier", 0))))
    if i.get("ammoType") and t in WEAPONS | {"Ammo", "AmmoNonEquipable"}:
        combat.append(("Ammo", esc(i["ammoType"].lstrip("$").replace("ammo_", ""))))
    for k, v in (i.get("modifiers") or {}).items():
        combat.append((f"{words(k)} modifier", f"{'+' if v > 0 else ''}{num(round(v * 100))}%"))
    if i.get("durability") and not i["durability"].get("repairable"):
        combat.append(("Repairable", "no"))

    body = header(i, "item", esc(TYPE_LABELS.get(t, words(t))), i.get("description"))
    body += kv(facts)
    body += section("Stats", quality_table(i) + kv(combat))
    if i.get("damageModifiers"):
        body += section("Resistances", modifiers_table(i["damageModifiers"]))
    if i.get("food"):
        f = i["food"]
        body += section("Food", kv([("Health", num(f.get("health", 0))), ("Stamina", num(f.get("stamina", 0))),
                                    ("Eitr", num(f["eitr"]) if f.get("eitr") else None),
                                    ("Healing", f'{num(f["regen"])} hp/tick' if f.get("regen") else None),
                                    ("Duration", duration(f["duration"]) if f.get("duration") else None)]))
    eff = []
    if i.get("consumeEffect"):
        eff.append(("When consumed", link("effect", i["consumeEffect"])))
    if i.get("equipEffect"):
        eff.append(("When equipped", link("effect", i["equipEffect"])))
    if i.get("set"):
        st = i["set"]
        eff.append((f"Set bonus ({st['size']} pieces)", link("effect", st["effect"]) if st.get("effect") else "—"))
        eff.append(("Set", " ".join(link("item", m) for m in set_members[st["name"]] if m != i["id"])))
    body += section("Effects", kv(eff))

    recipes = "".join(recipe_block(r, i.get("maxQuality", 1)) for r in crafted_by[i["id"]])
    body += section("Crafting", recipes)

    obtain = []
    for c in process_to[i["id"]]:
        obtain.append([f'{esc(PROCESS_LABELS.get(c["kind"], c["kind"]))} at {link("piece", c["station"])}',
                       f'{link("item", c["from"])} → ×{num(c["amount"])}', duration(c["time"])])
    body += section("Produced by", table(["How", "From", "Time"], obtain))

    drops = [[link("creature", cid), rng(d.get("min", 1), d.get("max", 1)), pct(d.get("chance", 1))]
             for cid, d in dropped_by[i["id"]]]
    body += section("Dropped by", table(["Creature", "Amount", "Chance"], drops))
    found = {}
    for s, amount in found_in[i["id"]]:
        found.setdefault((source_name(s), s["kind"], amount), None)
    body += section("Found in", table(["Source", "Kind", "Amount"],
                                      [[esc(n), esc(k), esc(a)] for n, k, a in sorted(found)]))

    used = [link("item", r["item"]) for r in used_in_recipe[i["id"]] if r.get("item")]
    used += [link("piece", p["id"]) for p in used_in_piece[i["id"]] if p["id"] != i["id"]]  # not "place on table"
    used += [link("item", c["to"]) for c in process_from[i["id"]]]
    body += section("Used in", reflist(used))
    if i.get("buildTable"):
        body += section("Builds", reflist(link("piece", p["id"]) for p in tool_pieces[i["id"]]))
    page(href("item", i["id"]), name_of("item", i["id"]), body, '<a href="items/index.html">Items</a>')


# --- creatures ------------------------------------------------------------------------------

def creature_page(c: dict) -> None:
    home = home_biome(c["id"])
    sub = " · ".join(x for x in (esc(BIOMES[home]) if home else "", "boss" if c.get("boss") else "") if x)
    sp = c.get("speed") or {}
    facts = [("Biome", ", ".join(esc(BIOMES[b]) for b in creature_biomes(c["id"]))),
             ("Faction", esc(words(c["faction"])) if c.get("faction") else None),
             ("Health", num(c["health"])),
             ("Speed", ", ".join(f"{k} {num(v)}" for k, v in sp.items())),
             ("Tameable", "yes" if c.get("tameable") else None),
             ("Afraid of fire", "yes" if c.get("afraidOfFire") else None),
             ("Avoids water", "yes" if c.get("avoidWater") else None),
             ("Group", esc(c["group"]) if c.get("group") else None)]
    body = header(c, "creature", sub) + kv(facts)
    body += section("Resistances", modifiers_table(c.get("damageModifiers")))
    attacks = []
    for a in c.get("attacks", []):
        w = ITEMS[a]
        atk = w.get("attack") or {}
        label = link("item", original(a)) if has_page("item", original(a)) else esc(clean(w.get("name")) or pretty_id(a))
        attacks.append([label, damages(w.get("damages")),
                        esc(words(atk.get("type", ""))), num(w["attackForce"]) if w.get("attackForce") else ""])
    body += section("Attacks", table(["Attack", "Damage", "Type", "Knockback"], attacks))
    gear = [link("item", original(x)) for x in c.get("equipment", []) if not ITEMS[x].get("internal")]
    body += section("Equipment", reflist(gear) + ('<p class=note>Enemy copies of player gear; '
                                                   'their stats can differ from the items linked here.</p>'
                                                   if any(ITEMS[x].get("enemyOnly") for x in c.get("equipment", [])) else ""))
    drops = [[link("item", d["item"]), rng(d.get("min", 1), d.get("max", 1)), pct(d.get("chance", 1))]
             for d in c.get("drops", [])]
    body += section("Drops", table(["Item", "Amount", "Chance"], drops))
    body += spawn_sections(spawns_of[c["id"]])
    page(href("creature", c["id"]), name_of("creature", c["id"]), body, '<a href="creatures/index.html">Creatures</a>')


def biome_list(s: dict) -> str:
    return ", ".join(esc(BIOMES.get(b, words(b))) for b in s.get("biomes", []))


def spawn_sections(spawns: list[dict]) -> str:
    """Where a creature comes from: ambient world spawns, locations and dungeons, raids, offspring."""
    by = defaultdict(list)
    for s in spawns:
        by[s.get("source", "world")].append(s)
    out = ""

    def as_variant(s):  # spawns of a merged copy (Troll_sleeping on the Troll page)
        note = variant_note("creature", s["creature"])
        return [f"as {esc(note)}"] if note else []

    rows = []
    for s in by["world"]:
        when = "day and night" if s.get("day") and s.get("night") else "day" if s.get("day") else "night"
        extra = as_variant(s)
        if s.get("requiredGlobalKey"):
            extra.append(f"after {esc(s['requiredGlobalKey'])}")
        if s.get("requiredEnvironments"):
            extra.append("weather: " + ", ".join(esc(e) for e in s["requiredEnvironments"]))
        if s.get("huntPlayer"):
            extra.append("hunts player")
        rows.append([biome_list(s), when, rng(*s["levels"]), rng(*s["groupSize"]), "; ".join(extra)])
    out += section("Spawns", table(["Biome", "Time", "Level", "Group", "Notes"], rows))

    rows = []
    for s in by["location"] + by["dungeon"]:
        notes = as_variant(s)
        if s["source"] == "dungeon":
            notes.append("in the dungeon")
        if s.get("respawning"):
            notes.append("respawns")
        if s.get("summon"):
            sm = s["summon"]
            notes.append("summoned with " + (link("item", sm["item"], sm.get("amount")) if sm.get("item") else "an offering"))
        rows.append([esc(pretty_id(s["location"])), biome_list(s), rng(*s["levels"]) if s.get("levels") else "",
                     "; ".join(notes)])
    out += section("Locations", table(["Location", "Biome", "Level", "Notes"], rows))

    rows = [[esc(pretty_id(s["event"])) + "".join(f" ({n})" for n in as_variant(s)), biome_list(s), rng(*s["levels"]),
             rng(*s["groupSize"]), esc(s.get("message") or "")] for s in by["raid"]]
    out += section("Raids", table(["Event", "Biome", "Level", "Group", "Message"], rows))

    born = [link("creature", s["parent"]) for s in by["offspring"]] + [link("item", s["item"]) for s in by["egg"]]
    out += section("Born from", reflist(born))
    return out


# --- pieces ---------------------------------------------------------------------------------

def piece_page(p: dict) -> None:
    sub = esc(words(p.get("category", "")))
    facts = [("Built with", " ".join(link("item", t) for t in p.get("tools", []))),
             ("Requires", link("piece", p["station"]) + " nearby" if p.get("station") else None),
             ("Extends", link("piece", p["extends"]) if p.get("extends") else None),
             ("Comfort", f'{num(p["comfort"]["value"])} ({esc(p["comfort"].get("group", "none"))})'
              if p.get("comfort") else None),
             ("Health", num(p["health"]) if p.get("health") else None),
             ("Material", esc(p["material"]) if p.get("material") else None),
             ("Only in", esc(p["onlyInBiome"]) if p.get("onlyInBiome") else None)]
    cs = p.get("craftingStation")
    if cs:
        facts += [("Build range", num(cs.get("buildRange"))), ("Needs roof", "yes" if cs.get("requiresRoof") else None)]
    body = header(p, "piece", sub, p.get("description")) + kv(facts)
    body += section("Cost", reflist(link("item", r["item"], r["amount"]) for r in p.get("resources", [])))
    body += section("Resistances", modifiers_table(p.get("damageModifiers")))
    body += section("Upgrades", reflist(link("piece", e["id"]) for e in extensions[p["id"]]))

    by_level = defaultdict(list)
    for r in crafted_at[p["id"]]:
        if r.get("item") and has_page("item", r["item"]):
            by_level[max(1, r.get("stationLevel", 1))].append(link("item", r["item"]))
    crafts = "".join(f"<h3>Level {lvl}</h3>{reflist(sorted(v, key=lambda s: re.sub('<[^>]+>', '', s)))}"
                     for lvl, v in sorted(by_level.items()))
    body += section("Crafts", crafts)
    conv = [[link("item", c["from"]), link("item", c["to"], c["amount"]), duration(c["time"]),
             link("item", c["fuel"]) if c.get("fuel") else ""] for c in process_at[p["id"]]]
    body += section("Converts", table(["Input", "Output", "Time", "Fuel"], conv))
    body += section("Enables building", reflist(link("piece", b["id"]) for b in built_at[p["id"]]))
    page(href("piece", p["id"]), name_of("piece", p["id"]), body, '<a href="pieces/index.html">Pieces</a>')


# --- status effects -------------------------------------------------------------------------

def effect_value(k: str, v) -> str:
    if isinstance(v, dict):
        return modifiers_table(v) if all(isinstance(x, str) for x in v.values()) else esc(json.dumps(v))
    if isinstance(v, list):
        return esc(", ".join(map(str, v)))
    if isinstance(v, (int, float)) and not isinstance(v, bool) and k.endswith("Multiplier"):
        return f"×{num(v)}"
    return esc(num(v)) if not isinstance(v, str) else esc(words(v))


def effect_page(e: dict) -> None:
    facts = [("Duration", duration(e["duration"]) if e.get("duration") else None),
             ("Cooldown", duration(e["cooldown"]) if e.get("cooldown") else None),
             ("Category", esc(e["category"]) if e.get("category") else None)]
    body = header(e, "effect", esc(e["type"]), e.get("tooltip")) + kv(facts)
    body += section("Stats", kv((words(k), effect_value(k, v)) for k, v in (e.get("stats") or {}).items()))
    body += section("From", reflist(f'{link("item", iid)} <span class=note>{esc(how)}</span>'
                                    for iid, how in effect_users[e["id"]]))
    page(href("effect", e["id"]), name_of("effect", e["id"]), body, '<a href="effects/index.html">Status effects</a>')


# --- indexes, search, home ------------------------------------------------------------------

def grid(kind: str, ids) -> str:
    ids = sorted(ids, key=lambda x: name_of(kind, x).lower())
    return '<ul class="grid">' + "".join(f"<li>{link(kind, x)}</li>" for x in ids) + "</ul>"


def index_pages() -> None:
    items = [i for i in ITEMS.values() if has_page("item", i["id"])]
    by_type = defaultdict(list)
    for i in items:
        by_type[i["type"]].append(i["id"])
    order = [t for t in TYPE_LABELS if t in by_type] + sorted(set(by_type) - set(TYPE_LABELS))
    toc = " · ".join(f'<a href="items/index.html#{t}">{esc(TYPE_LABELS.get(t, t))}</a>' for t in order)
    body = f'<h1>Items</h1><p class="toc">{toc}</p>' + "".join(
        f'<h2 id="{t}">{esc(TYPE_LABELS.get(t, t))}</h2>{grid("item", by_type[t])}' for t in order)
    page("items/index.html", "Items", body)

    groups = defaultdict(list)
    for c in CREATURES.values():
        if has_page("creature", c["id"]):
            groups[home_biome(c["id"]) or "Other"].append(c["id"])
    labels = {**BIOMES, "Other": "Other"}  # Other: boss phases, summons, prefabs worldgen never places
    order = [g for g in labels if g in groups]
    toc = " · ".join(f'<a href="creatures/index.html#{g}">{esc(labels[g])}</a>' for g in order)

    def bosses_first(ids):
        return "".join(grid("creature", part) for part in ([i for i in ids if CREATURES[i].get("boss")],
                                                            [i for i in ids if not CREATURES[i].get("boss")]) if part)
    body = f'<h1>Creatures</h1><p class="toc">{toc}</p>' + "".join(
        f'<h2 id="{g}">{esc(labels[g])}</h2>{bosses_first(groups[g])}' for g in order)
    page("creatures/index.html", "Creatures", body)

    groups = defaultdict(list)
    for p in PIECES.values():
        groups[words(p.get("category", "Misc"))].append(p["id"])
    body = "<h1>Pieces</h1>" + "".join(f"<h2>{esc(g)}</h2>{grid('piece', groups[g])}" for g in sorted(groups))
    page("pieces/index.html", "Pieces", body)

    body = "<h1>Status effects</h1>" + grid("effect", EFFECTS)
    page("effects/index.html", "Status effects", body)

    counts = {"items": len(items), "creatures": len(CREATURES), "pieces": len(PIECES), "effects": len(EFFECTS)}
    cards = "".join(f'<li><a href="{d}/index.html"><b>{n}</b>{d}</a></li>' for d, n in counts.items())
    body = (f'<div class="home"><h1>Mimir</h1><p class="sub">A Valheim reference, rebuilt from the game data on '
            f'every update. Valheim {esc(META["gameVersion"])}.</p><p class="hint">Press <kbd>/</kbd> to search.</p>'
            f'<ul class="cards">{cards}</ul></div>')
    page("index.html", "Valheim reference", body)


def search_index() -> None:
    entries = []
    labels = {"item": None, "creature": "Creature", "piece": "Piece", "effect": "Status effect"}
    for kind in KINDS:
        coll = {"item": ITEMS, "creature": CREATURES, "piece": PIECES, "effect": EFFECTS}[kind]
        for id_, e in coll.items():
            if not has_page(kind, id_):
                continue
            label = labels[kind] or TYPE_LABELS.get(e["type"], words(e["type"]))
            ic = icon_of(kind, e) if icon_of(kind, e) in HAVE_ICONS else ""
            entries.append([name_of(kind, id_), id_, href(kind, id_), ic, label])
    # same name, different prefabs (Troll / Troll_sleeping, enemy-only gear copies): show the id
    seen = defaultdict(int)
    for e in entries:
        seen[(e[0], e[4])] += 1
    for e in entries:
        if seen[(e[0], e[4])] > 1:
            e[4] = f"{e[4]} · {e[1]}"
    entries.sort(key=lambda x: (x[0].lower(), x[2]))
    (OUT / "search.json").write_text(json.dumps(entries, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def copy_assets() -> None:
    for f in STATIC.iterdir():
        shutil.copy2(f, OUT / f.name)
    used = {e.get("icon") for coll in (ITEMS, PIECES, EFFECTS) for e in coll.values()} & HAVE_ICONS
    (OUT / "icons").mkdir(exist_ok=True)
    for name in used:
        shutil.copy2(ICONS / f"{name}.png", OUT / "icons" / f"{name}.png")


def check_links() -> int:
    """Every href/src on every page must resolve to a written file (pages use <base> = site root)."""
    bad = 0
    pat = re.compile(r'(?:href|src)="([^"#]+)')
    for f in written:
        for target in pat.findall(f.read_text(encoding="utf-8")):
            if target.startswith(("http:", "https:", "../", "./")):
                continue
            if not (OUT / unquote(target)).exists():
                print(f"broken link in {f.relative_to(OUT)}: {target}", file=sys.stderr)
                bad += 1
    return bad


def main() -> int:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    if not HAVE_ICONS:
        print(f"warning: no icons in {ICONS}; pages will have no images (run make icons)", file=sys.stderr)
    for i in ITEMS.values():
        if has_page("item", i["id"]):
            item_page(i)
    for c in CREATURES.values():
        if has_page("creature", c["id"]):
            creature_page(c)
    for p in PIECES.values():
        piece_page(p)
    for e in EFFECTS.values():
        effect_page(e)
    index_pages()
    search_index()
    copy_assets()
    bad = check_links()
    print(f"site: {len(written)} pages, {len(list((OUT / 'icons').iterdir()))} icons -> {OUT}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
