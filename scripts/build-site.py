#!/usr/bin/env python3
"""Build the static site from data/ and the extracted icons. Stdlib only.

    scripts/build-site.py [data_dir] [icons_dir] [out_dir]
        # default: data/ + .cache/dump/public/icons -> .cache/site/public

One page per item, creature, piece and status effect, plus index pages and a client-side search
index (search.json, used by site/search.js). Hand-written Markdown pages in site/mechanics/ become the
Mechanics section (scripts/mechanics.py: renderer, formulas, charts; embedded tables read data/). Derived relations (crafted from, used in, dropped by,
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
sys.path.insert(0, str(Path(__file__).resolve().parent))
import mechanics  # noqa: E402  (renderer, charts and formulas for the Mechanics section)

DATA = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data"
ICONS = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / ".cache/dump/public/icons"
OUT = Path(sys.argv[3]) if len(sys.argv) > 3 else ROOT / ".cache/site/public"
STATIC = ROOT / "site"
MECH_SRC = STATIC / "mechanics"  # hand-written Markdown pages, see scripts/mechanics.py


def load(name: str):
    return json.loads((DATA / f"{name}.json").read_text(encoding="utf-8"))


META = load("meta")
SITE_NAME = "Mimir's Well"  # shown on the site; the project itself is "mimir"
ITEMS = {i["id"]: i for i in load("items")}
CREATURES = {c["id"]: c for c in load("creatures")}
PIECES = {p["id"]: p for p in load("pieces")}
EFFECTS = {e["id"]: e for e in load("status_effects")}
PLAYER = load("player")
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
    """A range for display; one value when the top isn't above the bottom (Ashlands trees have stackMin 2, stackMax 1,
    which DropTable.AddItemToList rolls as Random.Range(2, 2) = 2)."""
    return num(lo) if hi <= lo else f"{num(lo)}–{num(hi)}"


def drop_amount(d: dict) -> str:
    """Drop amounts are Random.Range(min, max) on ints, whose upper bound is exclusive (CharacterDrop.GenerateDropList)."""
    lo, hi = d.get("min", 1), d.get("max", 1)
    return rng(lo, hi - 1 if hi > lo else hi)


def stars(lo, hi) -> str:
    """Spawn data holds creature levels; stars = level - 1 (Character.SetLevel, 1 = no star)."""
    return rng(max(0, lo - 1), max(0, hi - 1))


def mech_link(page_id: str, text: str) -> str:
    """Link to a mechanics page; plain text if the page has no source (so data pages never link to nothing)."""
    if not (MECH_SRC / f"{page_id}.md").is_file():
        return esc(text)
    return f'<a href="mechanics/{page_id}.html">{esc(text)}</a>'


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
    return e is not None and not e.get("unobtainable") \
        and not (kind == "item" and (e.get("internal") or e.get("enemyOnly"))) and id_ not in MERGED[kind]


def original(item_id: str) -> str:
    """The player item an enemy-only copy imitates (FW_HelmetBronze -> HelmetBronze), else the id itself."""
    orig = item_id.split("_", 1)[-1]
    if ITEMS.get(item_id, {}).get("enemyOnly") and orig in ITEMS and ITEMS[orig].get("name") == ITEMS[item_id].get("name"):
        return orig
    return item_id


def base_name(kind: str, id_: str) -> str:
    e = entity(kind, id_)
    name = clean(e.get("name")) if e else ""
    return name if name and "$" not in name else pretty_id(id_)  # unresolved $token: the prefab id, prettified


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
    if s.get("name") and "$" not in s["name"]:
        return clean(s["name"])
    parent = next((p for p in SOURCES.values() if p.get("becomes") == s["id"]), None)
    if parent:
        return f"{source_name(parent)} ({s['kind']})"
    return pretty_id(s["id"])


def source_places(s: dict) -> str:
    """Where a source is found: a fish's biomes, a trader's locations (with biomes), or a world source's biomes,
    locations (dungeon rooms marked, long lists cut) and the pieces that plant or build it."""
    if s["kind"] == "trader":
        return ", ".join(f"{pretty_id(x['location'])} ({', '.join(BIOMES.get(b, words(b)) for b in x['biomes'])})"
                         for x in s["locations"])
    if s["kind"] == "fishing":
        return ", ".join(BIOMES.get(b, words(b)) for b in s.get("biomes", []))
    places = [BIOMES.get(b, words(b)) for b in s.get("biomes", [])]
    locs = list(dict.fromkeys(pretty_id(x["location"]) + (" dungeon" if x.get("dungeon") else "")
                              for x in s.get("locations", [])))
    places += locs[:4] + ([f"{len(locs) - 4} more locations"] if len(locs) > 4 else [])
    if s.get("placedBy"):
        places.append("planted or built: " + ", ".join(pretty_id(p) for p in s["placedBy"]))
    return ", ".join(places)


def key_label(key: str) -> str:
    """The condition behind a global key, for trader offers: the boss that sets it, Hildir's returned chest, or the key."""
    boss = next((c for c in CREATURES.values() if c.get("defeatKey") == key and "nochest" not in c["id"]), None)
    chest = ITEMS.get("chest_hildir" + key[6:]) if re.fullmatch(r"Hildir\d", key) else None
    return f"defeating {link('creature', boss['id'])}" if boss else \
        f"returning {link('item', chest['id'])}" if chest else esc(key)


# --- derived relations ----------------------------------------------------------------------

crafted_by = defaultdict(list)       # item -> recipes producing it
used_in_recipe = defaultdict(list)   # item -> recipes consuming it
# --- variants: prefabs sharing a display name ------------------------------------------------
# Identical copies (Troll / Troll_sleeping, FishRaw / FishAnglerRaw) merge into one page; the rest get a qualifier
# derived from the words their ids don't share: "Skeleton (Swamp, no bow)", "Kall Fimbulbringer (phase 2)".

ID_WORDS = {"NoArcher": "noarcher", "NonSleeping": "nonsleeping", "DualWield": "dualwield", "DeepNorth": "deepnorth",
            "deepNorth": "deepnorth"}
QUALIFIERS = {  # id word -> label; "" drops the word
    "sleeping": "sleeping", "nonsleeping": "awake", "nochest": "raid", "ranged": "archer", "noarcher": "no bow",
    "deepnorth": "Deep North", "meadows": "Meadows", "mountains": "Mountain", "mountain": "Mountain",
    "swamps": "Swamp", "swamp": "Swamp", "ashlands": "Ashlands", "dualwield": "dual-wield", "p2": "phase 2",
    "p3": "phase 3", "fem": "female", "tenta": "", "piece": "", "treasure": "", "loot": "", "notext": "no text",
    "itemstand": "", "itemstandh": "horizontal",
}


def id_words(id_: str) -> list[str]:
    for k, v in ID_WORDS.items():
        id_ = id_.replace(k, f"_{v}_")
    return [w.lower() for part in id_.split("_") for w in re.findall(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])", part)]


def qualifier(id_: str, others: list[str], name: str) -> str:
    """Words of the id that the other ids (or the display name) don't have, as labels."""
    common = set.intersection(*(set(id_words(o)) for o in [id_, *others]))
    named = set(re.findall(r"[a-z0-9]+", name.lower()))
    stems = {re.sub(r"\d+$", "", w) for o in others for w in id_words(o)}

    def label(w):
        m = re.fullmatch(r"([a-z]+?)0*(\d+)", w)  # corner2 next to corner, gift1 next to gift2: just the number
        return m.group(2) if m and m.group(1) in stems else QUALIFIERS.get(w, w)
    labels = [label(w) for w in id_words(id_) if w not in common and w not in named]
    return ", ".join(dict.fromkeys(x for x in labels if x))


def variants(kind: str, coll: dict, shown, primary=lambda id_: False, other="") -> tuple[dict, dict]:
    """(merged id -> page id, page id -> qualifier) for entities whose display names collide. When exactly one
    of a group is `primary` (the buildable piece), it keeps the plain name, and the others are at least `other`."""
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
        main = [p for p in pages if primary(p)]
        for id_ in pages:
            if len(main) == 1 and id_ == main[0]:
                continue
            q = qualifier(id_, [o for o in pages if o != id_], name) if len(pages) > 1 else ""
            if len(main) == 1 and not q:
                q = other
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
    "item", ITEMS, lambda i: not (ITEMS[i].get("internal") or ITEMS[i].get("enemyOnly") or ITEMS[i].get("unobtainable")))
MERGED["creature"], QUALIFIED["creature"] = variants("creature", CREATURES, lambda c: not CREATURES[c].get("unobtainable"))
MERGED["piece"], QUALIFIED["piece"] = variants("piece", PIECES, lambda p: not PIECES[p].get("unobtainable"), lambda p: bool(PIECES[p].get("tools")),
                                                    "world")


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
produced_by = defaultdict(list)      # item -> pieces making it on their own (beehive, sap extractor)
process_at = defaultdict(list)       # station -> conversions
dropped_by = defaultdict(list)       # item -> (creature id, drop)
found_in = defaultdict(list)         # item -> (source, text)
bait_for = defaultdict(list)         # bait item -> fish ids
sold_by = defaultdict(list)          # item -> (trader, offer)
effect_users = defaultdict(list)     # effect -> (item id, how)
spawns_of = defaultdict(list)        # creature -> spawn entries
tool_pieces = defaultdict(list)      # tool item -> pieces
set_members = defaultdict(list)      # set name -> items

for r in RECIPES:
    if ITEMS.get(r.get("item"), {}).get("unobtainable"):
        continue
    if r.get("item"):
        crafted_by[r["item"]].append(r)
    for res in r["resources"]:
        used_in_recipe[res["item"]].append(r)
    if r.get("station"):
        crafted_at[r["station"]].append(r)
for p in PIECES.values():
    if p.get("unobtainable"):
        continue
    for res in p.get("resources", []):
        used_in_piece[res["item"]].append(p)
    if p.get("station"):
        built_at[p["station"]].append(p)
    if p.get("extends"):
        extensions[p["extends"]].append(p)
    for t in p.get("tools", []):
        tool_pieces[t].append(p)
    if p.get("produces"):
        produced_by[p["produces"]["item"]].append(p)
for c in PROCESSING:
    process_from[c["from"]].append(c)
    if c.get("fuel") and c["fuel"] != c["from"]:
        process_from[c["fuel"]].append(c)
    process_to[c["to"]].append(c)
    process_at[c["station"]].append(c)
for c in CREATURES.values():
    if c.get("unobtainable"):
        continue
    for d in c.get("drops", []):
        dropped_by[d["item"]].append((c["id"], d))
for s in SOURCES.values():
    for o in s.get("sells", []):
        sold_by[o["item"]].append((s, o))
    for b in s.get("baits", []):
        bait_for[b["item"]].append(s["id"])
    if s.get("pickable"):
        pk = s["pickable"]
        if "oneOf" in pk:  # a treasure pile gives one of these at random
            for o in pk["oneOf"]:
                found_in[o["item"]].append((s, f"one of {len(pk['oneOf'])}: ×{rng(o.get('min', 1), o.get('max', 1))}"))
        else:
            found_in[pk["item"]].append((s, f"pick ×{num(pk.get('amount', 1))}"))
    dr = s.get("drops") or {}
    for it in dr.get("items", []):
        found_in[it["item"]].append((s, rng(it.get("min", 1), it.get("max", 1))))
    if s.get("becomes") in ITEMS:  # breaks into the item itself (Destructible.m_spawnWhenDestroyed)
        found_in[s["becomes"]].append((s, "1, when destroyed"))
for i in ITEMS.values():
    if i.get("internal") or i.get("enemyOnly") or i.get("unobtainable"):
        continue
    if i.get("consumeEffect"):
        effect_users[i["consumeEffect"]].append((i["id"], "consumed"))
    if i.get("equipEffect"):
        effect_users[i["equipEffect"]].append((i["id"], "equipped"))
    if (i.get("adrenaline") or {}).get("effect"):
        effect_users[i["adrenaline"]["effect"]].append((i["id"], "full adrenaline"))
    if i.get("set"):
        set_members[i["set"]["name"]].append(i["id"])
        if i["set"].get("effect"):
            effect_users[i["set"]["effect"]].append((i["id"], f"set of {i['set']['size']}"))
for s in SPAWNS:
    spawns_of[s["creature"]].append(s)
for kind, rels in {"item": [crafted_by, used_in_recipe, used_in_piece, process_from, process_to, dropped_by,
                            found_in, bait_for, sold_by, tool_pieces],
                   "creature": [spawns_of],
                   "piece": [crafted_at, built_at, extensions, process_at]}.items():
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
        parents = [s["parent"] for s in spawns_of[cid] if s.get("source") in ("offspring", "growup", "phase")]
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


def page(path: str, title: str, body: str, kind_label: str = "", scripts=()) -> None:
    depth = path.count("/")
    base = "../" * depth or "./"
    doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<base href="{base}">
<title>{esc(title)} · {esc(SITE_NAME)}</title>
<link rel="stylesheet" href="style.css">
<script src="search.js" defer></script>
{"".join(f'<script src="{esc(x)}" defer></script>' for x in scripts)}</head>
<body>
<header class="top">
  <a class="brand" href="index.html">{esc(SITE_NAME)}</a>
  <nav>{"".join(f'<a href="{d}/index.html">{d.capitalize()}</a>' for d in KINDS.values())}<a href="mechanics/index.html">Mechanics</a></nav>
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
    d = f'<p class="desc">{esc(clean(desc))}</p>' if desc and "$" not in desc else ""  # unresolved $token
    return (f'<div class="hero">{icon(icon_of(kind, e), "big")}<div><h1>{esc(name_of(kind, e["id"]))}</h1>'
            f'<p class="sub">{subtitle}</p>{d}</div></div>')


def modifiers_table(mods: dict, hide_tools: bool = False) -> str:
    """Ignore means zero damage (HitData.ApplyModifier), shown as Immune. Nearly every creature ignores chop and
    pickaxe (tool damage, irrelevant in combat), so creature pages drop those rows."""
    mods = {k: v for k, v in (mods or {}).items() if not (hide_tools and v == "Ignore" and k in ("chop", "pickaxe"))}
    if not mods:
        return ""
    return '<ul class="mods">' + "".join(
        f'<li class="m-{esc(v.lower())}"><span>{esc(k)}</span>{esc(words("Immune" if v == "Ignore" else v))}</li>'
        for k, v in mods.items()) + "</ul>"


def damages(d: dict) -> str:
    return ", ".join(f"{num(v)} {esc(k)}" for k, v in (d or {}).items())


# --- items ----------------------------------------------------------------------------------

def req_amount(res: dict, q: int) -> int:
    if q <= 1:
        return res.get("amount", 0)
    n = (q - 1) if q < 4 else 4 + (q - 4) / 2
    return math.floor(n * res.get("perLevel", 0) + (res.get("amount", 0) if res.get("upgrader") else 0))


MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()


def season_note(x: dict) -> str:
    """"Seasonal: Yule (1 Dec – 6 Jan)" for a piece or recipe that is only enabled in a season."""
    s = x.get("season")
    if not s:
        return ""
    d, e = s["start"], s["end"]
    return f'Seasonal: {esc(s["name"])} ({d[0]} {MONTHS[d[1] - 1]} – {e[0]} {MONTHS[e[1] - 1]})'


def recipe_block(r: dict, max_q: int) -> str:
    station = link("piece", r["station"]) if r.get("station") else "by hand"
    base_lvl = max(1, r.get("stationLevel", 1))
    normal = [x for x in r["resources"] if not x.get("upgrader")]
    upgrader = [x for x in r["resources"] if x.get("upgrader")]
    out = f'<p>{station}{f" (level {base_lvl})" if r.get("station") else ""}'
    out += f' · makes ×{r["amount"]}</p>' if r["amount"] > 1 else "</p>"
    if r.get("season"):
        out += f"<p class=note>{season_note(r)}</p>"
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
    if t in WEAPONS and not i.get("tamedOnly"):
        for label, a in (("DPS", i.get("attack")), ("Secondary DPS", i.get("secondaryAttack"))):
            if a and a.get("cycle") and (d := mechanics.dps(mechanics.hit_damage(dmg), a)) is not None:
                cols.append((label, d, mechanics.dps(mechanics.hit_damage(dpl), a) or 0))  # linear in damage
        a, ammo = i.get("attack") or {}, best_ammo(i)
        if (a.get("draw") or a.get("reload")) and ammo:  # bows and crossbows: weapon + ammo damage, skill-dependent
            extra = mechanics.hit_damage(ammo.get("damages", {}))
            for skill in (0, 100):
                if (d := mechanics.dps(mechanics.hit_damage(dmg) + extra, a, skill)) is not None:
                    cols.append((f"DPS (skill {skill})", d, mechanics.dps(mechanics.hit_damage(dpl), a, skill) or 0))
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
    rows = [[str(q)] + [num(round(b + (q - 1) * p, 1)) for _, b, p in cols] for q in range(1, mq + 1)]
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
    if a.get("thrown"):
        parts.append("thrown (the weapon lands where it hits)")
    if a.get("draw"):
        parts.append(f"full draw {num(a['draw'])} s ({num(mechanics.draw_time(a['draw'], 100))} s at skill 100)")
    if a.get("reload"):
        parts.append(f"reload {num(a['reload'])} s ({num(mechanics.reload_time(a['reload'], 100))} s at skill 100)")
    if (a.get("draw") or a.get("reload")) and (c0 := mechanics.attack_cycle(a, 0)):
        parts.append(f"{num(round(c0, 2))} s per shot ({num(round(mechanics.attack_cycle(a, 100), 2))} s at skill 100)")
    if a.get("cycle"):
        hits = sum(c["hits"] for c in a["chain"])
        n = len(a["chain"])
        parts.append((f"{n}-attack combo in {num(a['cycle'])} s" if n > 1 else f"{num(a['cycle'])} s")
                     + (f" ({hits} hits)" if hits != n else ""))
    return ", ".join(p for p in parts if p)


ATTACK_VARIANTS = {"hildir", "frozen", "deep", "north", "ashlands", "nochest", "summoned"}  # which creature, not which move
ATTACK_ABBREV = {"l": "left", "r": "right", "h": "horizontal", "v": "vertical"}


def id_words(s: str) -> list[str]:
    """CamelCase / snake_case id -> words; "2HAxe" -> 2H, Axe."""
    out = []
    for w in re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|[0-9]+", s):
        if out and out[-1].isdigit() and w == "H":
            out[-1] += "H"
        else:
            out.append(w)
    return out


def attack_label(cid: str, aid: str, strict: bool = False) -> str:
    """A name for an internal attack item from its id: the game's own names are placeholders shared across
    creatures ("Club", "slap"). Drops the owner's words, for an aspect the boss's id (Aspect_Elder uses
    aspect_gd_king_*), the "attack" segment and variant words. `strict` drops only the first word, to tell apart two
    attacks of one creature that would get the same label."""
    rest = re.sub(r"^aspect_", "", aid, flags=re.I)
    owners = sorted((c for c in CREATURES if rest.lower().startswith(c.lower() + "_") or
                     rest.startswith(c) and rest[len(c):len(c) + 1].isupper()), key=len)
    if owners and cid.startswith("Aspect_") and not strict:  # a boss's aspect reuses the boss's attacks
        rest = rest[len(owners[-1]):].lstrip("_")
    own = {"aspect"} | ({id_words(aid)[0].lower()} if strict else {w.lower() for w in id_words(cid)})
    dropped_attack, words_ = False, []
    for seg in rest.split("_"):
        if seg.lower() == "attack" and not strict:
            dropped_attack = True
        else:
            words_ += id_words(seg)
    keep = [w for w in words_ if w.lower() not in own | ATTACK_VARIANTS
            and not (len(w) > 3 and any(len(o) > 3 and o in w.lower() for o in own))]
    keep = [w for n, w in enumerate(keep) if not n or w.lower() != keep[n - 1].lower()]  # "Staff heal heal"
    if not keep:
        return "Attack" if dropped_attack or not words_ else words_[-1].capitalize()
    text_ = " ".join(ATTACK_ABBREV.get(w.lower(), w if w[0].isdigit() or len(w) > 1 and w.isupper() else w.lower())
                     for w in keep)
    return text_[0].upper() + text_[1:]


def attack_labels(c: dict) -> dict[str, str]:
    """Labels for a creature's internal attacks, unique within the creature."""
    ids = [a for a in c.get("attacks", []) if ITEMS[a].get("internal")]
    labels = {a: attack_label(c["id"], a) for a in ids}
    for a in ids:
        if list(labels.values()).count(labels[a]) > 1:
            labels[a] = attack_label(c["id"], a, strict=True)
    return labels


def attack_damage(w: dict) -> str:
    """A creature attack's damage: the item's, or what its projectiles and area effects deal (`hits`)."""
    if not (hits := w.get("hits")):
        return damages(w.get("damages"))
    if hits[0]["kind"] == "none":
        return "—"
    return " + ".join(damages(h["damages"]) + ("" if h["kind"] == "hit" or len(hits) == 1 and h["kind"] == "projectile"
                                                else f' <span class="qty">{h["kind"]}</span>') for h in hits)


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
            combat.append(("Adrenaline", f'+{num(i.get("blockAdrenaline", 0))} per block, '
                                         f'+{num(i.get("parryAdrenaline", 0))} per parry'))
        if i.get("tamedOnly"):
            combat.append(("Hits", "only tamed creatures"))
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
    stat_note = ""
    if t == "Shield" or (t in WEAPONS and i.get("block") and i.get("skill") == "Blocking"):
        stat_note = f'<p class="note">How block power, parrying and stagger work: {mech_link("blocking", "Blocking")}.</p>'
    elif t in WEAPONS and any(mechanics.attack_cycle(a) for a in (i.get("attack"), i.get("secondaryAttack"))):
        ammo = best_ammo(i) if (i.get("attack") or {}).get("draw") or (i.get("attack") or {}).get("reload") else None
        stat_note = ((f'<p class="note">Bow and crossbow DPS with {link("item", ammo["id"])}, the hardest-hitting '
                      f'ammo.</p>') if ammo else "")
        stat_note += f'<p class="note">How attack speed and DPS are worked out: {mech_link("attack-speed", "Attack speed")}.</p>'
    elif t in ARMOR and i.get("armor"):
        stat_note = (f'<p class="note">How armor reduces damage: {mech_link("damage-types", "Damage types and resistances")}.</p>')
    body += section("Stats", quality_table(i) + kv(combat) + stat_note)
    if i.get("damageModifiers"):
        body += section("Resistances", modifiers_table(i["damageModifiers"]) +
                        f'<p class="note">What the levels mean: {mech_link("damage-types", "Damage types and resistances")}.</p>')
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
    if adr := i.get("adrenaline"):
        if adr.get("max"):
            eff.append(("Max adrenaline", f'+{num(adr["max"])}'))
        if adr.get("effect"):
            eff.append(("When adrenaline is full", link("effect", adr["effect"])))
    if i.get("set"):
        st = i["set"]
        eff.append((f"Set bonus ({st['size']} pieces)", link("effect", st["effect"]) if st.get("effect") else "—"))
        eff.append(("Set", " ".join(link("item", m) for m in set_members[st["name"]] if m != i["id"])))
    if i.get("adrenaline"):
        eff.append(("How it fills", mech_link("adrenaline", "Adrenaline")))
    body += section("Effects", kv(eff))

    recipes = "".join(recipe_block(r, i.get("maxQuality", 1)) for r in crafted_by[i["id"]])
    body += section("Crafting", recipes)

    obtain = []
    for c in process_to[i["id"]]:
        obtain.append([f'{esc(PROCESS_LABELS.get(c["kind"], c["kind"]))} at {link("piece", c["station"])}',
                       f'{link("item", c["from"])} → ×{num(c["amount"])}', duration(c["time"])])
    for p in produced_by[i["id"]]:
        pr = p["produces"]
        where = " near " + esc(pretty_id(pr["connectsTo"]["id"])) if pr.get("connectsTo") else ""
        obtain.append([f'Produced by {link("piece", p["id"])}{where}', "", f'{duration(pr["secPerUnit"])} each, up to ×{num(pr["max"])}'])
    body += section("Produced by", table(["How", "From", "Time"], obtain))
    laid = [s["parent"] for s in spawns_of[i["id"]] if s.get("source") == "offspring"]
    body += section("Laid by", reflist(link("creature", c) for c in laid))

    fish = SOURCES.get(i["id"])
    if fish and fish["kind"] == "fishing":
        how = "Caught with " + ", ".join(link("item", b["item"]) for b in fish["baits"])
        body += section("Fishing", f'<p>{how}{" in " + esc(source_places(fish)) if fish.get("biomes") else ""}.</p>')
    body += section("Bait for", reflist(link("item", f) for f in bait_for[i["id"]]))

    offers = [[esc(source_name(t)), link("item", "Coins", o["price"]) + (f" for ×{num(o['stack'])}" if o["stack"] > 1 else ""),
               key_label(o["requiredKey"]) if o.get("requiredKey") else "", esc(source_places(t))]
              for t, o in sold_by[i["id"]]]
    body += section("Sold by", table(["Trader", "Price", "After", "Where"], offers))

    drops = [[link("creature", cid), drop_amount(d), pct(d.get("chance", 1))]
             for cid, d in dropped_by[i["id"]]]
    body += section("Dropped by", table(["Creature", "Amount", "Chance"], drops) +
                    (f'<p class="note">Amounts and chances are for an unstarred creature: {mech_link("drops", "Drops")}.</p>'
                     if drops else ""))
    found = {}
    for s, amount in found_in[i["id"]]:
        found.setdefault((source_name(s), s["kind"], amount, source_places(s)), None)
    body += section("Found in", table(["Source", "Kind", "Amount", "Where"],
                                      [[esc(n), esc(k), esc(a), esc(w)] for n, k, a, w in sorted(found)]))

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
             ("Stars", f'health ×(1 + stars), damage ×(1 + 0.5 × stars): {mech_link("creature-levels", "Creature levels")}'
              if not c.get("boss") else None),
             ("Speed", ", ".join(f"{k} {num(v)}" for k, v in sp.items())),
             ("Tameable", "yes" if c.get("tameable") else None),
             ("Afraid of fire", "yes" if c.get("afraidOfFire") else None),
             ("Avoids water", "yes" if c.get("avoidWater") else None),
             ("Group", esc(c["group"]) if c.get("group") else None)]
    body = header(c, "creature", sub) + kv(facts)
    mods = modifiers_table(c.get("damageModifiers"), hide_tools=True)
    body += section("Resistances", mods + (f'<p class="note">What the levels mean: '
                                           f'{mech_link("damage-types", "Damage types and resistances")}.</p>' if mods else ""))
    attacks, labels = [], attack_labels(c)
    for a in c.get("attacks", []):
        w = ITEMS[a]
        atk = w.get("attack") or {}
        label = (link("item", original(a)) if has_page("item", original(a))
                 else esc(labels.get(a) or clean(w.get("name")) or pretty_id(a)))
        attacks.append([label, attack_damage(w),
                        esc(words(atk.get("type", ""))), num(w["attackForce"]) if w.get("attackForce") else ""])
    body += section("Attacks", table(["Attack", "Damage", "Type", "Knockback"], attacks))
    gear = [link("item", original(x)) for x in c.get("equipment", []) if not ITEMS[x].get("internal")]
    body += section("Equipment", reflist(gear) + ('<p class=note>Enemy copies of player gear; '
                                                   'their stats can differ from the items linked here.</p>'
                                                   if any(ITEMS[x].get("enemyOnly") for x in c.get("equipment", [])) else ""))
    drops = [[link("item", d["item"]) + (' <span class="qty">×stars</span>' if d.get("levelMultiplier") else "")
              + (' <span class="qty">×players</span>' if d.get("onePerPlayer") else ""),
              drop_amount(d), pct(d.get("chance", 1))] for d in c.get("drops", [])]
    body += section("Drops", table(["Item", "Amount", "Chance"], drops) + (
        f'<p class="note">Drops marked ×stars grow with the creature\'s stars, and low chances are pseudo-random: '
        f'{mech_link("drops", "Drops")}.</p>' if drops else ""))
    body += spawn_sections(spawns_of[c["id"]])
    page(href("creature", c["id"]), name_of("creature", c["id"]), body, '<a href="creatures/index.html">Creatures</a>')


STARS_TH = mech_link("creature-levels", "Stars")


def biome_list(s: dict) -> str:
    return ", ".join(esc(BIOMES.get(b, words(b))) for b in s.get("biomes", []))


def spawn_sections(spawns: list[dict]) -> str:
    """Where a creature comes from: ambient world spawns, locations and dungeons, raids, offspring, summons and boss phases."""
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
        if s.get("altBiome"):
            extra.append(f"in {esc(words(s['altBiome']))} patches")
        if s.get("requiredGlobalKey"):
            extra.append(f"after {esc(s['requiredGlobalKey'])}")
        if s.get("requiredEnvironments"):
            extra.append("weather: " + ", ".join(esc(e) for e in s["requiredEnvironments"]))
        if s.get("huntPlayer"):
            extra.append("hunts player")
        rows.append([biome_list(s), when, stars(*s["levels"]), rng(*s["groupSize"]), "; ".join(extra)])
    out += section("Spawns", table(["Biome", "Time", STARS_TH, "Group", "Notes"], rows))

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
        rows.append([esc(pretty_id(s["location"])), biome_list(s), stars(*s["levels"]) if s.get("levels") else "",
                     "; ".join(notes)])
    out += section("Locations", table(["Location", "Biome", STARS_TH, "Notes"], rows))

    rows = [[esc(pretty_id(s["event"])) + "".join(f" ({n})" for n in as_variant(s)), biome_list(s), stars(*s["levels"]),
             rng(*s["groupSize"]), esc(s.get("message") or "")] for s in by["raid"]]
    out += section("Raids", table(["Event", "Biome", STARS_TH, "Group", "Message"], rows))

    born = [link("creature", s["parent"]) for s in by["offspring"] + by["growup"]] + \
           [link("item", s["item"]) for s in by["egg"]]
    out += section("Born from", reflist(born))
    summoned = [link("creature", s["parent"]) + (f" ({link('item', s['item'])})" if s.get("item") else "")
                if s.get("parent") else link("item", s["item"]) for s in by["summon"]]
    out += section("Summoned by", reflist(summoned))
    out += section("Phase of", reflist(link("creature", s["parent"]) for s in by["phase"]))
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
    if p.get("season"):
        body += f"<p class=note>{season_note(p)}</p>"
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
    pr = p.get("produces")
    if pr:
        rows = [("Produces", link("item", pr["item"])), ("Rate", f'one per {duration(pr["secPerUnit"])}, holds up to {num(pr["max"])}'),
                ("Works in", ", ".join(esc(BIOMES.get(b, words(b))) for b in pr.get("biomes", []))),
                ("Needs", esc(pretty_id(pr["connectsTo"]["id"])) + " (" + ", ".join(
                    esc(BIOMES.get(b, words(b))) for b in pr["connectsTo"].get("biomes", [])) + ")"
                 if pr.get("connectsTo") else None)]
        body += section("Produces", kv(rows))
    body += section("Enables building", reflist(link("piece", b["id"]) for b in built_at[p["id"]]))
    if p.get("locations"):  # not buildable, but standing in the world
        body += section("Found in", f'<p>{esc(source_places({"kind": "world", "locations": p["locations"]}))}</p>')
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


# --- mechanics pages ------------------------------------------------------------------------
# Hand-written Markdown in site/mechanics/*.md (format and directives: scripts/mechanics.py). Generated tables are
# embedded with {{directives}} that read data/, so values never go stale; the prose and formulas are the part that
# was verified against the decompiled game code.

MECH_PAGES: list[dict] = []  # {id, title, summary, order}, filled by mechanics_pages(), used by the index and search


def mech_resolve(scheme: str, id_: str):
    if scheme == "mechanic":
        return f"mechanics/{id_}.html" if (MECH_SRC / f"{id_}.md").is_file() else None
    id_ = MERGED[scheme].get(id_, id_)
    return href(scheme, id_) if has_page(scheme, id_) else None


def block_shields() -> str:
    """Every shield with its block stats and the block power it gives at skill 0 and 100 (parry in the last column)."""
    rows = []
    for i in sorted((x for x in ITEMS.values() if x["type"] == "Shield" and has_page("item", x["id"])),
                    key=lambda x: (x.get("block", 0), x["id"])):
        base, per, q = i.get("block", 0), i.get("blockPerLevel", 0), i.get("maxQuality", 1)
        parry = i.get("parryBonus", 0)
        p = parry if parry > 1 else 1
        rows.append([link("item", i["id"]), num(base), num(per), f"×{num(parry)}" if parry > 1 else "none",
                     num(mechanics.block_power(base, per, 1, 0)), num(mechanics.block_power(base, per, 1, 100)),
                     num(mechanics.block_power(base, per, q, 100)),
                     num(mechanics.block_power(base, per, q, 100, p)) if parry > 1 else "–"])
    return table(["Shield", "Block", "Per level", "Parry bonus", "Power, q1 skill 0", "q1 skill 100",
                  "max quality, skill 100", "…parried"], rows, "num")


def block_resist_creatures() -> str:
    """Creatures with Immune, Very resistant or Very weak damage types (Ignore, which every creature has for chop and
    pickaxe, is left out, as on creature pages)."""
    cols = [("Immune", "Immune"), ("VeryResistant", "Very resistant"), ("VeryWeak", "Very weak")]
    rows = []
    for c in sorted(CREATURES.values(), key=lambda x: name_of("creature", x["id"]).lower()):
        if not has_page("creature", c["id"]):
            continue
        mods = c.get("damageModifiers") or {}
        cells = [esc(", ".join(k for k, v in mods.items() if v == key)) for key, _ in cols]
        if any(cells):
            rows.append([link("creature", c["id"])] + cells)
    return table(["Creature"] + [label for _, label in cols], rows)


def block_resist_gear() -> str:
    rows = [[link("item", i["id"]), modifiers_table(i["damageModifiers"])]
            for i in sorted(ITEMS.values(), key=lambda x: name_of("item", x["id"]).lower())
            if i.get("damageModifiers") and has_page("item", i["id"])]
    return table(["Item", "Damage modifiers"], rows)


def block_star_spawns() -> str:
    """The highest star count each creature can spawn with, from its spawn entries (spawn data holds levels)."""
    top = {}
    for s in SPAWNS:
        if s.get("levels") and has_page("creature", MERGED["creature"].get(s["creature"], s["creature"])):
            cid = MERGED["creature"].get(s["creature"], s["creature"])
            top[cid] = max(top.get(cid, 0), s["levels"][1] - 1)
    by = defaultdict(list)
    for cid, n in top.items():
        if n >= 1:
            by[n].append(cid)
    out = ""
    for n in sorted(by):
        names = reflist(link("creature", c) for c in sorted(by[n], key=lambda x: name_of("creature", x).lower()))
        body = (f"<summary>Up to {n} star{'s' if n > 1 else ''}: {len(by[n])} "
                f"creature{'s' if len(by[n]) > 1 else ''}</summary>{names}")
        out += f"<details{'' if len(by[n]) > 20 else ' open'}>{body}</details>"
    return out


def block_star_odds() -> str:
    """Star odds for the spawn ranges that occur in the data (levels min-max) at the default 10% and SpawnArea's 15%."""
    ranges = sorted({tuple(x["levels"]) for x in SPAWNS if x.get("levels") and x["levels"][1] > 1 and x["levels"][0] >= 1})
    rows = []
    for lo, hi in ranges:
        for chance in (10, 15) if hi > lo else (10,):  # a fixed level doesn't depend on the chance
            dist = mechanics.level_distribution(chance, lo, hi)
            rows.append([f"{stars(lo, hi)} stars", f"{chance}%" if hi > lo else "–"] +
                        [pct(dist[lv]) if lv in dist else "–" for lv in range(1, 6)])
    return table(["Spawn range", "Chance per star"] + [f"{n} stars" if n != 1 else "1 star" for n in range(0, 5)], rows, "num")


def block_guaranteed_stars() -> str:
    """Spawn entries whose minimum level is above 1: always starred. One row per creature, source kind and star range."""
    found: dict[tuple, list[str]] = {}
    for s in SPAWNS:
        if s.get("levels") and s["levels"][0] > 1:
            cid = MERGED["creature"].get(s["creature"], s["creature"])
            if not has_page("creature", cid):
                continue
            where = {"raid": pretty_id(s.get("event", "")), "world": ", ".join(BIOMES.get(b, words(b)) for b in s.get("biomes", []))
                     }.get(s["source"], pretty_id(s.get("location", "")))
            found.setdefault((name_of("creature", cid).lower(), cid, s["source"], stars(*s["levels"])), []).append(where)
    rows = []
    for (_, cid, source, st), wheres in sorted(found.items()):
        wheres = list(dict.fromkeys(wheres))
        text = ", ".join(wheres[:3]) + (f" and {len(wheres) - 3} more" if len(wheres) > 3 else "")
        rows.append([link("creature", cid), esc(source), esc(text), st])
    return table(["Creature", "Source", "Where", "Stars"], rows)


def block_pseudo_drops() -> str:
    """Drops whose base chance is 0.3 or less, the ones that use the pseudo-random countdown for an unstarred kill."""
    by = defaultdict(list)
    for c in CREATURES.values():
        if not has_page("creature", c["id"]):
            continue
        for d in c.get("drops", []):
            if d.get("chance", 1) <= 0.3:
                by[d["item"]].append((c["id"], d["chance"]))
    rows = [[link("item", item), " ".join(f'{link("creature", c)}<span class="qty">{pct(p)}</span>' for c, p in sorted(v))]
            for item, v in sorted(by.items(), key=lambda kv: name_of("item", kv[0]).lower())]
    n = sum(len(v) for v in by.values())
    return f"<details><summary>{n} drops of {len(rows)} items have a base chance of 30% or less</summary>" + \
        table(["Item", "Creatures and chance"], rows) + "</details>" if rows else ""


def block_pseudo_table() -> str:
    rows = [[pct(p), str(mechanics.pseudo_gap_max(p)), pct(mechanics.pseudo_rate(p))] for p in (0.05, 0.1, 0.25, 0.3)]
    return table(["Base chance", "Most kills between drops", "Long-run drops per kill"], rows, "num")


def block_drops_example() -> str:
    """The Troll's drop list at 0, 1 and 2 stars, computed with the rules on the Drops page from data/."""
    c = CREATURES.get("Troll")
    if not c or not c.get("drops"):
        return ""
    rows = []
    for d in c["drops"]:
        cells = []
        for st in range(3):
            n = mechanics.star_multipliers(st)["drops"] if d.get("levelMultiplier") else 1
            p = min(1.0, d.get("chance", 1) * n)
            pseudo = d.get("chance", 1) * n <= 0.3
            lo, hi = d.get("min", 1), d.get("max", 1)
            amt = rng(lo * n, (hi - 1 if hi > lo else hi) * n)
            cells.append(f"{amt} at {pct(p)}" + (" (pseudo-random)" if pseudo else ""))
        rows.append([link("item", d["item"])] + cells)
    return table(["Item", "0 stars", "1 star", "2 stars"], rows)


def block_upgrade_costs() -> str:
    rows = [[str(q), "base amount" if q == 1 else f"{num(mechanics.upgrade_cost_multiplier(q))} × per level",
             f"{num(mechanics.upgrade_cost_multiplier(q))}" if q > 1 else "–", f"+{q - 1}"] for q in range(1, 7)]
    return table(["Quality", "Cost of a resource", "Multiplier", "Station level"], rows, "num")


def block_upgrade_example() -> str:
    item = next((ITEMS[x] for x in ("SwordIron",) if x in ITEMS), None)
    rec = next((r for r in RECIPES if item and r.get("item") == item["id"]), None)
    if not rec:
        return ""
    cols = [(r, max(1, rec.get("stationLevel", 1))) for r in rec["resources"] if not r.get("upgrader")]
    q_max = item.get("maxQuality", 1)
    rows = [[str(q), str(cols[0][1] + q - 1)] + [num(req_amount(r, q)) for r, _ in cols] for q in range(1, q_max + 1)]
    head = ["Quality", "Station level"] + [esc(name_of("item", r["item"])) for r, _ in cols]
    return (f'<p>Example, {link("item", item["id"])} (from the recipe in data/): each resource column is '
            f'<code>amount</code> then <code>perLevel</code> times the multiplier.</p>' + table(head, rows, "num"))


def block_trinkets() -> str:
    """Every item with an adrenaline bar: what it adds to max adrenaline, the effect it fires when full, how long that
    lasts, and how long a full bar takes to drain from just below full (delay not included)."""
    adr = PLAYER["adrenaline"]
    rows = []
    for i in sorted((x for x in ITEMS.values() if x.get("adrenaline") and has_page("item", x["id"])),
                    key=lambda x: (x["adrenaline"].get("max", 0), x["id"])):
        a = i["adrenaline"]
        e = EFFECTS.get(a.get("effect")) or {}
        mx = a.get("max", 0)
        drain = mechanics.adrenaline_drain_time(mx, mx, adr["degen"]) if mx and adr.get("degen") else 0
        rows.append([link("item", i["id"]), num(mx), link("effect", e["id"]) if e else "—",
                     duration(e["duration"]) if e.get("duration") else "—", duration(round(drain)) if drain else "—"])
    return table(["Trinket", "Max adrenaline", "When full", "Lasts", "Full bar drains in"], rows, "num")


def block_adrenaline_attacks() -> str:
    """Player weapons whose attacks give other than the default 1 adrenaline per hit, or give adrenaline on use."""
    rows = []
    for i in sorted((x for x in ITEMS.values() if x["type"] in WEAPONS and has_page("item", x["id"])),
                    key=lambda x: name_of("item", x["id"]).lower()):
        for label, a in (("primary", i.get("attack")), ("secondary", i.get("secondaryAttack"))):
            if not a:
                continue
            hit, use = a.get("adrenaline", 0), a.get("useAdrenaline", 0)
            ranged = a.get("type") == "Projectile"
            if use or (not ranged and hit != 1):
                rows.append([link("item", i["id"]), label, esc(words(a.get("type", ""))),
                             "projectile" if ranged else num(hit), num(use) if use else ""])
    return table(["Weapon", "Attack", "Type", "Per hit", "On use"], rows, "num")


def block_attack_speed() -> str:
    """Every player weapon attack with a known cycle: hits, time, and DPS at max quality (tooltip damage, skill roll 1)."""
    rows = []
    weapons = (x for x in ITEMS.values() if x["type"] in WEAPONS and has_page("item", x["id"]) and not x.get("tamedOnly"))
    for i in sorted(weapons, key=lambda x: (words(x.get("skill") or ""), name_of("item", x["id"]).lower())):
        q = i.get("maxQuality", 1)
        dmg = {k: i.get("damages", {}).get(k, 0) + (q - 1) * i.get("damagesPerLevel", {}).get(k, 0)
               for k in mechanics.COMBAT_DAMAGE}
        for label, a in (("primary", i.get("attack")), ("secondary", i.get("secondaryAttack"))):
            d = mechanics.dps(mechanics.hit_damage(dmg), a) if a and a.get("cycle") else None
            if d is None:
                continue
            rows.append([link("item", i["id"]), esc(words(i.get("skill") or "")), label,
                         num(sum(c["hits"] for c in a["chain"])), num(a["cycle"]),
                         num(round(mechanics.combo_damage(mechanics.hit_damage(dmg), a), 1)), num(round(d, 1))])
    return table(["Weapon", "Skill", "Attack", "Hits", "Seconds", "Damage", "DPS"], rows, "num")


def best_ammo(i: dict) -> dict | None:
    """The obtainable ammo of the weapon's ammo type with the most combat damage per hit. None if no ammo of the
    type does damage (the fishing rod draws like a bow, but casts bait)."""
    ammo = [x for x in ITEMS.values() if x["type"] == "Ammo" and x.get("ammoType") == i.get("ammoType")
            and has_page("item", x["id"]) and mechanics.hit_damage(x.get("damages", {}))]
    return max(ammo, key=lambda x: (mechanics.hit_damage(x.get("damages", {})), x["id"]), default=None)


def block_attack_speed_ranged() -> str:
    """Bows and crossbows at max quality with their best ammo: time per shot and DPS at skill 0 and 100."""
    rows = []
    for i in sorted((x for x in ITEMS.values() if x["type"] in WEAPONS and has_page("item", x["id"])),
                    key=lambda x: (words(x.get("skill") or ""), name_of("item", x["id"]).lower())):
        a, ammo = i.get("attack") or {}, best_ammo(i)
        if not (a.get("draw") or a.get("reload")) or not ammo or not mechanics.attack_cycle(a):
            continue
        q = i.get("maxQuality", 1)
        hit = mechanics.hit_damage({k: i.get("damages", {}).get(k, 0) + (q - 1) * i.get("damagesPerLevel", {}).get(k, 0)
                                    for k in mechanics.COMBAT_DAMAGE}) + mechanics.hit_damage(ammo.get("damages", {}))
        rows.append([link("item", i["id"]), num(a.get("draw") or a.get("reload")),
                     num(round(mechanics.attack_cycle(a, 0), 2)), num(round(mechanics.attack_cycle(a, 100), 2)),
                     link("item", ammo["id"]), num(round(mechanics.combo_damage(hit, a), 1)),
                     num(round(mechanics.dps(hit, a, 0), 1)), num(round(mechanics.dps(hit, a, 100), 1))])
    return table(["Weapon", "Draw / reload", "Seconds (skill 0)", "Seconds (skill 100)", "Ammo", "Damage",
                  "DPS (skill 0)", "DPS (skill 100)"], rows, "num")


def block_adrenaline_blockers() -> str:
    """Shields and weapons whose block or parry adrenaline differs from the ItemDrop defaults (2 and 5)."""
    rows = []
    for i in sorted((x for x in ITEMS.values() if x["type"] in WEAPONS | {"Shield"} and has_page("item", x["id"])),
                    key=lambda x: name_of("item", x["id"]).lower()):
        b, pa = i.get("blockAdrenaline", 0), i.get("parryAdrenaline", 0)
        if (b, pa) != (2, 5):
            rows.append([link("item", i["id"]), num(b), num(pa)])
    return table(["Item", "Per block", "Per parry"], rows, "num")


def block_adrenaline_sources() -> str:
    """What adds or removes adrenaline. Player values from data/player.json; the guardian power's 10 is a code constant
    (Player.m_adrenalineGuardianPower, not serialized)."""
    adr = PLAYER["adrenaline"]
    rows = [("Melee hit", "the attack's per-hit value, for each creature hit", "Attack.DoMeleeAttack"),
            ("Area attack", "the attack's per-hit value, once if an enemy is hit", "Attack.DoAreaAttack"),
            ("Projectile hit", "the projectile's value (2 by default), when it damages a creature", "Projectile.OnHit"),
            ("Attack used", "the attack's on-use value; again per burst for attacks that pay per burst",
             "Attack.OnAttackTrigger"),
            ("Block", "the blocker's per-block value, unless it is a parry; even if the block breaks", "Humanoid.BlockAttack"),
            ("Parry", "the blocker's per-parry value, if the block holds", "Humanoid.BlockAttack"),
            ("Perfect dodge", num(adr.get("perfectDodge", 0)), "Player.RPC_HitWhileDodging"),
            ("Stagger an enemy", num(adr.get("staggerEnemy", 0)), "Character.AddStaggerDamage"),
            ("Guardian power used", "10", "Player.ActivateGuardianPower"),
            ("Melee attack hits nothing", num(adr.get("attackMiss", 0)), "Attack.DoMeleeAttack"),
            ("Hit taken without blocking", num(adr.get("nonBlockDamage", 0)), "Character.RPC_Damage")]
    return table(["Event", "Adrenaline", "Method"], [[esc(a), esc(b), f"<code>{c}</code>"] for a, b, c in rows])


def block_adrenaline_effects() -> str:
    """Status effects that change adrenaline gain (SE_Stats.m_adrenalineModifier)."""
    return reflist(f'{link("effect", e["id"])} <span class=note>{"+" if v > 0 else ""}{num(round(v * 100))}% gain</span>'
                   for e in sorted(EFFECTS.values(), key=lambda x: x["id"])
                   if (v := (e.get("stats") or {}).get("adrenalineModifier")) and has_page("effect", e["id"]))


def mech_blocks() -> dict:
    return {"shields": block_shields, "resistant-creatures": block_resist_creatures, "resistant-gear": block_resist_gear,
            "star-spawns": block_star_spawns, "star-odds": block_star_odds, "guaranteed-stars": block_guaranteed_stars,
            "pseudo-drops": block_pseudo_drops, "pseudo-table": block_pseudo_table,
            "drops-example": block_drops_example, "upgrade-costs": block_upgrade_costs,
            "upgrade-example": block_upgrade_example,
            "trinkets": block_trinkets, "attack-speed": block_attack_speed,
            "attack-speed-ranged": block_attack_speed_ranged, "adrenaline-attacks": block_adrenaline_attacks,
            "adrenaline-blockers": block_adrenaline_blockers, "adrenaline-effects": block_adrenaline_effects,
            "adrenaline-sources": block_adrenaline_sources,
            "adrenaline-chart": lambda: mechanics.adrenaline_chart(PLAYER["adrenaline"]),
            "chart": lambda name: mechanics.CHARTS[name]()}


def mechanics_pages() -> None:
    sources = sorted(MECH_SRC.glob("*.md")) if MECH_SRC.is_dir() else []
    for f in sources:
        meta, text = mechanics.parse_front_matter(f.read_text(encoding="utf-8"))
        ctx = mechanics.Ctx(mech_resolve, mech_blocks())
        try:
            content = mechanics.render(text, ctx)
        except ValueError as e:
            raise SystemExit(f"{f.name}: {e}")
        cites = [x.strip() for x in meta.get("sources", "").split(";") if x.strip()]
        cite = (f'<aside class="cite"><b>Verified</b> against the decompiled game code of Valheim {esc(META["gameVersion"])}: '
                + ", ".join(f"<code>{esc(x)}</code>" for x in cites) + ". "
                'Statements marked <i>Inferred</i> are reasoning from the code or data, not checked in the game.</aside>'
                if cites else "")
        title = meta.get("title", f.stem)
        MECH_PAGES.append({"id": f.stem, "title": title, "summary": meta.get("summary", ""),
                           "order": int(meta.get("order", 99))})
        body = (f'<h1>{esc(title)}</h1><p class="sub">{esc(meta.get("summary", ""))}</p>'
                f'<div class="mech">{content}</div>{cite}')
        page(f"mechanics/{f.stem}.html", title, body, '<a href="mechanics/index.html">Mechanics</a>', ctx.scripts)
    MECH_PAGES.sort(key=lambda p: (p["order"], p["title"]))
    items = "".join(f'<li><a href="mechanics/{p["id"]}.html">{esc(p["title"])}</a><span>{esc(p["summary"])}</span></li>'
                    for p in MECH_PAGES)
    body = (f'<h1>Mechanics</h1><p class="sub">How the game works, for Valheim {esc(META["gameVersion"])}.</p>'
            f'<p>Derived from the decompiled game code: every formula names the method it comes from, and anything '
            f'inferred rather than verified is marked. Tables and charts are generated from the same game data as the '
            f'rest of the site.</p>'
            f'<ul class="mechlist">{items}</ul>')
    page("mechanics/index.html", "Mechanics", body)


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
        if has_page("piece", p["id"]):
            groups[words(p.get("category", "Misc"))].append(p["id"])
    body = "<h1>Pieces</h1>" + "".join(f"<h2>{esc(g)}</h2>{grid('piece', groups[g])}" for g in sorted(groups))
    page("pieces/index.html", "Pieces", body)

    body = "<h1>Status effects</h1>" + grid("effect", EFFECTS)
    page("effects/index.html", "Status effects", body)

    counts = {"items": len(items), "creatures": len(CREATURES), "pieces": len(PIECES), "effects": len(EFFECTS)}
    cards = "".join(f'<li><a href="{d}/index.html"><b>{n}</b>{d}</a></li>' for d, n in counts.items())
    cards += f'<li><a href="mechanics/index.html"><b>{len(MECH_PAGES)}</b>mechanics</a></li>'
    body = (f'<div class="home"><h1>{esc(SITE_NAME)}</h1><p class="sub">A Valheim reference, rebuilt from the game data on '
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
    entries += [[p["title"], p["id"], f"mechanics/{p['id']}.html", "", "Mechanics"] for p in MECH_PAGES]
    entries.sort(key=lambda x: (x[0].lower(), x[2]))
    (OUT / "search.json").write_text(json.dumps(entries, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def copy_assets() -> None:
    for f in STATIC.iterdir():
        if f.is_dir():
            if f != MECH_SRC:  # mechanics/ holds page sources, not assets
                shutil.copytree(f, OUT / f.name)
        else:
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
        if has_page("piece", p["id"]):
            piece_page(p)
    for e in EFFECTS.values():
        effect_page(e)
    mechanics_pages()
    index_pages()
    search_index()
    copy_assets()
    bad = check_links()
    print(f"site: {len(written)} pages, {len(list((OUT / 'icons').iterdir()))} icons -> {OUT}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
