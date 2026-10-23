#!/usr/bin/env python3
"""The well (#25, #68): the tech tree drawn as a cylinder, one band per progression stage, on the home page.

    scripts/well.py [DATA_DIR] [--audit]     # stats; --audit lists the needs left out of the graph and its roots

graph() picks the nodes and edges, layout() places them, markup() writes the HTML that build-site.py puts on the home
page (with site/well.js and the .well rules in site/style.css); tests/test_well.py tests each."""
import collections
import html
import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
S = ["Meadows", "BlackForest", "Swamp", "Mountain", "Plains", "Mistlands", "AshLands", "DeepNorth", "PostGame"]
NAMES = {"BlackForest": "Black Forest", "AshLands": "Ashlands", "DeepNorth": "Deep North", "PostGame": "Post-game"}
COL = {"Meadows": "#a6d77f", "BlackForest": "#4fa064", "Swamp": "#a07a52", "Mountain": "#cfdbe5",
       "Plains": "#dcc283", "Mistlands": "#a893d6", "AshLands": "#e0603f", "DeepNorth": "#8fcdf2", "PostGame": "#e8c65a"}
GEAR_SKILLS = ["Swords", "Axes", "Clubs", "Knives", "Spears", "Polearms", "Unarmed", "Bows", "Crossbows",
               "ElementalMagic", "BloodMagic"]
ARMOR = ["Helmet", "Chest", "Legs", "Shoulder"]
IGNORED_DAMAGE = {"chop", "pickaxe", "spirit"}
COOKING_STATIONS = {"piece_cauldron", "piece_cookingstation", "piece_cookingstation_iron", "piece_oven", "fermenter",
                    "piece_MeadCauldron", "piece_preptable", "windmill"}
# layout: page width, band padding, row height, radius, tilt (px); slots at least NMIN per ring; a ring over CROWD
# gets more room, over SPLIT two rows; SPLAY turns each ring by up to that share of a slot; BETA pulls important nodes
# to the front; SAMPLES points per edge
W, BANDPAD, ROWH, R, TILT, NMIN, CROWD, SPLIT, SPLAY, BETA, SAMPLES = 1200, 60, 76, 440, 44, 9, 18, 20, .4, 1.5, 12
GATE = GEAR = 1000
BOSS = GEAR + 1  # the boss is the last thing done in a tier


def load(data_dir: Path) -> dict:
    """The data/ files the well reads, as lists."""
    rows = lambda f: (lambda d: d if isinstance(d, list) else list(d.values()))(json.loads((data_dir / f"{f}.json").read_text()))
    return {f: rows(f) for f in ("items", "pieces", "creatures", "sources", "locations")}


def graph(data: dict) -> SimpleNamespace:
    """The well's nodes (`sel`: (kind, id)) and edges (`par`: node -> what it needs), and what layout() and page()
    need besides."""
    ent, items = {}, {i["id"]: i for i in data["items"]}
    for f, k in (("items", "item"), ("pieces", "piece"), ("creatures", "creature")):
        for e in data[f]:
            if not (e.get("unobtainable") or e.get("internal") or e.get("enemyOnly")) and e.get("stage"):
                ent[(k, e["id"])] = e
    stage = lambda x: S.index(ent[x]["stage"])
    srcs = {x["id"]: x for x in data["sources"]}
    cooking = COOKING_STATIONS | {k for (t, k), e in ent.items() if t == "piece" and e.get("extends") in COOKING_STATIONS}
    bosses = {x for x, e in ent.items() if x[0] == "creature" and e.get("boss") and e["via"].get("how") != "phase"}

    def way_needs(x):
        return [(k, n[k], n.get("amount")) for n in ent[x].get("via", {}).get("needs", [])
                for k in ("item", "piece", "creature") if k in n]

    # 1-2: every obtainable item but consumables, trophies and what cooking stations make (food and mead intermediates)
    cooked = lambda x: any(k == "piece" and i in cooking for k, i, _ in way_needs(x))
    # ...and fishing: fish, bait, the rod and the hat made of fish lead nowhere else (their catch drops and the trophies
    # only bait needs then connect to nothing and are dropped)
    fishing = {"FishingRod", "HelmetFishingHat"} | {i for s in srcs.values() if s["kind"] == "fishing"
                                                    for i in [s["id"]] + [b["item"] for b in s.get("baits", [])]}
    # ...and food in the wider sense: fireworks (lit in a Fireplace, m_fireworkItemList, which data/ doesn't have) and
    # what only goes into food (the Bog Witch's seasonings and ingredients)
    users = collections.defaultdict(list)
    for u in ent:
        for k, i, _ in way_needs(u):
            users[(k, i)].append(u)
    eaten = lambda x: x[1].startswith("FireworksRocket") or ent[x].get("type") == "Consumable" or cooked(x)
    food_only = lambda x: bool(users[x]) and all(eaten(u) for u in users[x])
    # ...and Hildir's quest chests and cosmetic clothing: a helmet, chest or legs with base armour 1 or less, but the
    # Rag set a player starts in (Hildir's clothes, seasonal hats; capes stay)
    taken = {t["item"] for s in srcs.values() for t in s.get("takes", [])}
    cosmetic = lambda e: e.get("type") in ("Helmet", "Chest", "Legs") and e.get("armor", 0) <= 1 and not e["id"].startswith("ArmorRags")
    skip = fishing | taken | {x for (k, x), e in ent.items() if k == "item" and cosmetic(e)}
    sel = {x for x, e in ent.items() if x[0] == "item" and e.get("type") != "Trophy" and not eaten(x) and not food_only(x)
           and x[1] not in skip}
    # 3: bosses (their drops are items already), ships and carts
    sel |= bosses | {x for x, e in ent.items() if x[0] == "piece" and "Transportation" in e.get("tags", [])}
    # ...but keep a consumable, trophy or cooked item something kept needs (Blueberries for Berserker armour, the Deer
    # trophy for Eikthyr's altar), and 4: the non-cooking pieces they need; one fixed point, so an item only a piece
    # needs is kept too (the Asksvin trophy for the Galdr table's upgrade)
    todo = list(sel)
    while todo:
        x = todo.pop()
        for k, i, _ in way_needs(x):
            if (k, i) not in ent or (k, i) in sel:
                continue
            food = x[0] == "item" and ent[x].get("type") in ("Consumable", "Material", "Misc")
            if k == "item" and i not in skip or k == "piece" and not (i in cooking and food):
                sel.add((k, i))
                todo.append((k, i))

    def boss_of(c):  # a boss's later phase stands for the boss (the Frozen King's third phase drops the Crown Jewel)
        seen = set()
        while c not in bosses and c in ent and c not in seen and ent[c].get("via", {}).get("how") == "phase":
            seen.add(c)
            c = ("creature", ent[c]["via"]["from"])
        return c

    # 5: links to what each needs (no source nodes: an item gathered with a tool links straight to the tool)
    par = {}
    for x in sel:
        ns = {boss_of((k, i)) if k == "creature" else (k, i) for k, i, _ in way_needs(x)}
        par[x] = {n for n in ns if n in sel}
    # ...and a crafted item that only goes into one processed item folds into it (the Deep North casts, forged at the
    # Frost Foundry: the gear needs the mould, Gold and the rest directly)
    n_users = collections.Counter(q for ps in par.values() for q in ps)
    for x in sorted(x for x in sel if ent[x].get("via", {}).get("how") == "process"):
        for c in [q for q in par[x] if q[0] == "item" and ent[q].get("via", {}).get("how") == "craft" and n_users[q] == 1]:
            par[x] = par[x] - {c} | par.pop(c)
            sel.discard(c)
    # ...and dead ends: an item or piece nothing kept needs, unless it is an end in itself: gear (any item type but
    # Material and Misc, or one with an attack: siege ammo), a door key, a saddle (Tameable.m_saddleItem, not in
    # data/), a ship or cart, a boss. Dropping one can leave what only it needed a dead end too (Turnip, then its sapling)
    door_keys = {loc["key"] for loc in data["locations"] if loc.get("key")}
    end = lambda x: x[0] == "creature" or "Transportation" in ent[x].get("tags", []) or x[0] == "item" and (
        ent[x].get("type") not in ("Material", "Misc") or ent[x].get("attack") or x[1] in door_keys or x[1].startswith("Saddle"))
    while dead := {x for x in sel if not end(x)} - {q for x in sel for q in par[x]}:
        sel -= dead
        for x in dead:
            del par[x]
    # 6: drop what connects to nothing
    kids = collections.defaultdict(set)
    for x, ps in par.items():
        for q in ps:
            kids[q].add(x)
    lonely = {x for x in sel if not par.get(x) and not kids[x]}
    sel -= lonely
    par = {x: ps & sel for x, ps in par.items() if x in sel}
    kids = collections.defaultdict(set)
    for x, ps in par.items():
        for q in ps:
            kids[q].add(x)

    # top gear: per stage, the strongest crafted weapon of each skill, the best armour piece per slot and shield
    def power(i):
        if i["type"] in ARMOR:
            return i.get("armor", 0)
        if i["type"] == "Shield":
            return i.get("block", 0)
        return sum(v for k, v in i.get("damages", {}).items() if k not in IGNORED_DAMAGE)

    best = {}
    for x in sorted(sel):
        e = ent[x]
        if x[0] != "item" or e["via"].get("how") not in ("craft", "process") or e["type"] in ("Ammo", "AmmoNonEquipable"):
            continue
        slot = e["type"] if e["type"] in ARMOR + ["Shield"] else e.get("skill") if e.get("skill") in GEAR_SKILLS else None
        if slot and power(e) > 0:
            key = (e["stage"], slot)
            if key not in best or power(e) > power(ent[best[key]]):
                best[key] = x
    return SimpleNamespace(ent=ent, items=items, srcs=srcs, sel=sel, par=par, kids=kids, bosses=bosses,
                           gear=set(best.values()), lonely=lonely, stage=stage, way_needs=way_needs, boss_of=boss_of,
                           cooked=cooked, cooking=cooking)


def layout(g: SimpleNamespace) -> SimpleNamespace:
    """Places the nodes on a cylinder seen from slightly above. Each stage is a band as tall as its rings; inside it a
    ring per rank (longest path inside the stage; top gear, then the boss, last). Round each ring the most important
    nodes face the viewer: importance = how many nodes need it, directly or not. Returns the rings (in drawing order),
    each node's angle `theta`, height `ypos` and slot width per unit of radius `slot`, the `bands` and the height `H`."""
    ent, sel, par, kids, stage = g.ent, g.sel, g.par, g.kids, g.stage
    anc_memo, desc_memo = {}, {}

    def anc(x):
        if x not in anc_memo:
            anc_memo[x] = set().union(*[{q} | anc(q) for q in par[x]]) if par[x] else set()
        return anc_memo[x]

    def desc(x):
        if x not in desc_memo:
            desc_memo[x] = set().union(*[{k} | desc(k) for k in kids[x]]) if kids[x] else set()
        return desc_memo[x]

    rank = {}
    for x in sorted(sel, key=lambda x: (stage(x), len(anc(x)), x)):
        if x in g.bosses:
            rank[x] = BOSS
        elif x in g.gear:
            rank[x] = GEAR
        else:
            rank[x] = max([rank[p] + 1 for p in par[x] if stage(p) == stage(x) and rank.get(p, GATE) < GATE], default=0)
    for si in range(len(S)):  # a node with no parent in its tier (moulds, drops, loot) takes the least crowded rank
        # above its first user, the later on a tie; the most constrained go first. Its users have a parent in the tier
        tier = [x for x in sel if stage(x) == si and rank[x] < GATE]
        last = max([rank[x] for x in tier], default=0)
        r = lambda k: last + 1 if rank[k] >= GATE else rank[k]
        first = {x: min(r(k) for k in kids[x] if stage(k) == si) for x in tier
                 if not any(stage(p) == si for p in par[x]) and any(stage(k) == si for k in kids[x])}
        load = collections.Counter(rank[x] for x in tier if x not in first)
        for x in sorted(first, key=lambda x: (first[x], ent[x].get("name", ""), x)):
            rank[x] = min(range(first[x]), key=lambda q: (load[q], -q))
            load[rank[x]] += 1

    imp = {x: len(desc(x)) for x in sel}
    byrank = collections.defaultdict(lambda: collections.defaultdict(list))
    for x in sorted(sel):
        byrank[stage(x)][rank[x]].append(x)
    ring_h = lambda n: 2 * ROWH if n > SPLIT else ROWH * (1 + .5 * max(0, n - CROWD) / CROWD)  # a crowded ring gets
    # more room; one over SPLIT is drawn as two staggered rows
    counts = collections.Counter(ent[x]["stage"] for x in ent if x[0] in ("item", "piece"))
    rings, ypos, bands, y = [], {}, [], TILT + 24
    for si, s in enumerate(S):
        top, y = y, y + BANDPAD
        for rk in sorted(byrank[si]):
            ring = byrank[si][rk]
            rings.append(ring)
            for x in ring:
                ypos[x] = y + ring_h(len(ring)) / 2
            y += ring_h(len(ring))
        bands.append((s, top, counts[s], sum(len(v) for v in byrank[si].values())))

    # angles: a ring's nodes take evenly spaced slots on an arc centred on the front (the whole circle from NMIN
    # nodes); each pass, a node wants the angle where its neighbours are, pulled to the front by importance (log share
    # of the stage's most important node), and takes the free slot nearest it, the most important first
    wrap = lambda a: (a + math.pi) % math.tau - math.pi
    # A ring is turned by its own fraction of a slot (golden-ratio steps, within ±SPLAY) so that consecutive rings
    # don't stack their nodes, and the edges between them, straight above one another.
    phase = {id(r): ((j * .6180339887) % 1 - .5) * 2 * SPLAY for j, r in enumerate(rings)}
    slots = lambda ring: [(j - (len(ring) - 1) / 2 + phase[id(ring)]) * math.tau / max(len(ring), NMIN) for j in range(len(ring))]
    nb = {x: sorted(par[x] | kids[x]) for x in sel}  # sorted: the same sums whatever the hash seed
    top_imp = collections.defaultdict(int)
    for x in sel:
        top_imp[stage(x)] = max(top_imp[stage(x)], imp[x])
    front = {x: math.log1p(imp[x]) / math.log1p(top_imp[stage(x)]) if top_imp[stage(x)] else 0 for x in sel}
    theta = {}
    for ring in rings:  # start: by importance, the most important in the middle, the rest to alternate sides
        order = sorted(ring, key=lambda x: (-imp[x], ent[x].get("name", ""), x))
        ring[:] = order[1::2][::-1] + order[0::2]
        theta.update(zip(ring, slots(ring)))
    for it in range(24):
        for ring in (rings if it % 2 == 0 else rings[::-1]):
            want = {x: math.atan2(sum(math.sin(theta[n]) for n in nb[x]),
                                  sum(math.cos(theta[n]) for n in nb[x]) + BETA * front[x] * max(1, len(nb[x])))
                    for x in ring}
            free = slots(ring)
            for x in sorted(ring, key=lambda x: (-imp[x], ent[x].get("name", ""), x)):  # the most important choose first
                theta[x] = min(free, key=lambda a: abs(wrap(a - want[x])))
                free.remove(theta[x])
    slot = {x: math.tau / max(len(ring), NMIN) for ring in rings for x in ring}  # slot width per unit of radius
    for ring in rings:  # a ring over SPLIT nodes: every other node, round the circle, half a row up or down
        if len(ring) > SPLIT:
            for j, x in enumerate(sorted(ring, key=lambda x: theta[x])):
                ypos[x] += ROWH / 2 * (1 if j % 2 else -1)
                slot[x] *= 2  # its neighbours in the row are two slots away
    return SimpleNamespace(rings=rings, theta=theta, ypos=ypos, slot=slot, bands=bands, H=y + TILT + 24, rank=rank, imp=imp)


def icon(g: SimpleNamespace, x: tuple) -> str | None:
    """A node's icon; a creature's is its trophy, from it or a later phase, else its last phase's last drop (the Frozen
    King has no trophy: the Crown Jewel)."""
    if x[0] != "creature":
        return g.ent[x].get("icon")
    phases = [x] + sorted(c for c in g.ent if c[0] == "creature" and c != x and g.boss_of(c) == x)
    drops = [g.items[d["item"]] for c in phases for d in g.ent[c].get("drops", []) if d.get("item") in g.items]
    return next((i.get("icon") for i in drops if i.get("type") == "Trophy"), drops[-1].get("icon") if drops else None)


def stage_bosses(g: SimpleNamespace) -> dict:
    """Stage index -> the boss that closes it (the home page's "Up to" picker); Post-game has none."""
    return {g.stage(b): b for b in sorted(g.bosses)}


def markup(g: SimpleNamespace, lay: SimpleNamespace, icons: set, links: dict | None = None) -> str:
    """The well's HTML for the home page (build-site.py): nodes as links placed by CSS from their angle (site/style.css,
    the first render and without JavaScript), the band names (linked through `links`: stage -> href), two canvases and
    the fog for site/well.js, and its data in <script id="well-data">."""
    ent, items, theta, ypos, slot, H = g.ent, g.items, lay.theta, lay.ypos, lay.slot, lay.H
    e, links = html.escape, links or {}
    order = [x for ring in lay.rings for x in ring]
    idx = {x: n for n, x in enumerate(order)}
    nodes = []
    for x in order:
        ic = icon(g, x)
        href = f'{ {"item": "items", "piece": "pieces", "creature": "creatures"}[x[0]]}/{x[1]}.html'
        name = ent[x].get("name", x[1])
        cls = "node" + (" boss" if x in g.bosses else " gear" if x in g.gear else "")
        img = f'<img src="icons/{ic}.png" alt="" loading="lazy" draggable="false">' if ic in icons else ""
        nodes.append(f'<a href="{href}" class="{cls}" data-n="{idx[x]}" draggable="false" title="{e(name)}" '
                     f'style="--a:{theta[x]:.4f}rad;--k:{slot[x]:.4f};top:{ypos[x]:.0f}px;--tier:{COL[ent[x]["stage"]]}">'
                     f'<span class="ic">{img}</span><span class="lb">{e(name)}</span></a>')
    name = lambda s: f'<a href="{links[s]}">{e(NAMES.get(s, s))}</a>' if s in links else e(NAMES.get(s, s))
    labels = "".join(f'<div class="bandname" style="top:{top + 12:.0f}px;--tier:{COL[s]}">{name(s)}'
                     f'<span>{n_shown} of {n_all}</span></div>' for s, top, n_all, n_shown in lay.bands)
    data = {"a": [round(theta[x], 4) for x in order], "y": [round(ypos[x]) for x in order],
            "c": [g.stage(x) for x in order], "k": [round(slot[x], 4) for x in order],
            "col": [COL[s] for s in S], "bands": [round(top) for _, top, _, _ in lay.bands] + [round(H - TILT - 24)],
            "par": [sorted(idx[p] for p in g.par[x]) for x in order]}
    blob = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")  # can't close the <script> early
    return (f'<div class="well" style="height:{H:.0f}px"><canvas class="back"></canvas><div class="fog"></div>'
            f'<canvas class="front"></canvas>{labels}{"".join(nodes)}</div>\n'
            f'<script type="application/json" id="well-data">{blob}</script>')


def audit(g: SimpleNamespace) -> None:
    """Needs left out of the graph, and roots by how they're got."""
    miss, ex = collections.Counter(), collections.defaultdict(list)
    for x in g.sel:
        for k, i, _ in g.way_needs(x):
            n = g.boss_of((k, i)) if k == "creature" else (k, i)
            if n in g.sel:
                continue
            why = ("cooking piece" if k == "piece" and i in g.cooking else "creature" if k == "creature" else
                   "consumable" if g.ent.get(n, {}).get("type") == "Consumable" else "cooked item" if n in g.ent and g.cooked(n)
                   else "unstaged/unknown" if n not in g.ent else "OTHER")
            miss[why] += 1
            ex[why].append(f"{x[1]}<-{i}")
    print("left-out needs:", dict(miss), file=sys.stderr)
    for w in ("OTHER", "unstaged/unknown", "cooked item", "consumable", "cooking piece"):
        if ex[w]:
            print(" ", w, ex[w][:15], file=sys.stderr)
    roots = collections.defaultdict(list)
    for x in g.sel:
        if not g.par[x]:
            v = g.ent[x].get("via", {})
            sd = g.srcs.get(v.get("from"), {})
            roots[f'{x[0]} {v.get("how")}{"/" + sd["kind"] if sd else ""}'].append(x[1])
    for k, v in sorted(roots.items(), key=lambda kv: -len(kv[1])):
        print(f"  root {k}: {len(v)}", v[:10], file=sys.stderr)


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    g = graph(load(Path(args[0]) if args else ROOT / "data"))
    print(f"well: {len(g.sel)} nodes, {sum(len(p) for p in g.par.values())} edges, "
          f"{[sum(1 for x in g.sel if g.stage(x) == i) for i in range(len(S))]} per stage, {len(g.gear)} top gear, "
          f"{len(g.lonely)} unconnected dropped", file=sys.stderr)
    if "--audit" in argv:
        audit(g)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
