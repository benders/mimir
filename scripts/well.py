"""Prototype (#25): the 'well' tech tree. Reads data/, writes .cache/site/public/well.html (uses the built site's icons;
run `make site` first, then `python3 scripts/well.py [--audit]` and open http://localhost:8000/well.html)."""
import json, collections, html, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / ".cache/site/public/well.html"
MIN_DEG = int(sys.argv[1]) if len(sys.argv) > 1 else 6
L = lambda f: (lambda d: d if isinstance(d, list) else list(d.values()))(json.load(open(ROOT / f"data/{f}.json")))
S = ["Meadows", "BlackForest", "Swamp", "Mountain", "Plains", "Mistlands", "AshLands", "DeepNorth", "PostGame"]
NAMES = {"BlackForest": "Black Forest", "AshLands": "Ashlands", "DeepNorth": "Deep North", "PostGame": "Post-game"}
COL = {"Meadows": "#a6d77f", "BlackForest": "#4fa064", "Swamp": "#a07a52", "Mountain": "#cfdbe5",
       "Plains": "#dcc283", "Mistlands": "#a893d6", "AshLands": "#e0603f", "DeepNorth": "#8fcdf2", "PostGame": "#e8c65a"}
ICONS = {p.stem for p in (ROOT / ".cache/site/public/icons").glob("*.png")}
GEAR_SKILLS = ["Swords", "Axes", "Clubs", "Knives", "Spears", "Polearms", "Unarmed", "Bows", "Crossbows",
               "ElementalMagic", "BloodMagic"]
ARMOR = ["Helmet", "Chest", "Legs", "Shoulder"]
IGNORED_DAMAGE = {"chop", "pickaxe", "spirit"}

ent, items = {}, {i["id"]: i for i in L("items")}
for f, k in (("items", "item"), ("pieces", "piece"), ("creatures", "creature")):
    for e in L(f):
        if not (e.get("unobtainable") or e.get("internal") or e.get("enemyOnly")) and e.get("stage"):
            ent[(k, e["id"])] = e
stage = lambda x: S.index(ent[x]["stage"])


def needs(x):
    out = []
    for n in ent[x].get("via", {}).get("needs", []):
        k = next(t for t in ("item", "piece", "creature") if t in n)
        if (k, n[k]) in ent:
            out.append((k, n[k]))
    return out


srcs = {x["id"]: x for x in L("sources")}
COOKING = {"piece_cauldron", "piece_cookingstation", "piece_cookingstation_iron", "piece_oven", "fermenter",
           "piece_MeadCauldron", "piece_preptable", "windmill"}
COOKING |= {k for (t, k), e in ent.items() if t == "piece" and e.get("extends") in COOKING}
bosses = {x for x, e in ent.items() if x[0] == "creature" and e.get("boss") and e["via"].get("how") != "phase"}


def way_needs(x):
    return [(k, n[k], n.get("amount")) for n in ent[x].get("via", {}).get("needs", [])
            for k in ("item", "piece", "creature") if k in n]


# 1-2: every obtainable item but consumables and what cooking stations make (food and mead intermediates)
cooked = lambda x: any(k == "piece" and i in COOKING for k, i, _ in way_needs(x))
# ...and fishing: fish, bait, the rod and the hat made of fish lead nowhere else (their catch drops and the trophies
# only bait needs then connect to nothing and are dropped)
FISHING = {"FishingRod", "HelmetFishingHat"} | {i for s in srcs.values() if s["kind"] == "fishing"
                                                for i in [s["id"]] + [b["item"] for b in s.get("baits", [])]}
sel = {x for x, e in ent.items() if x[0] == "item" and e.get("type") != "Consumable" and not cooked(x)
       and x[1] not in FISHING}
# 3: bosses (their drops are items already)
sel |= bosses
# ...but keep a consumable or cooked item something kept needs (Blueberries for Berserker armour, bait for fish)
todo = list(sel)
while todo:
    x = todo.pop()
    for k, i, _ in way_needs(x):
        if k == "item" and (k, i) in ent and (k, i) not in sel and i not in FISHING:
            sel.add((k, i))
            todo.append((k, i))
# 4: the non-cooking pieces those need, and the pieces those pieces need
todo = list(sel)
while todo:
    x = todo.pop()
    for k, i, _ in way_needs(x):
        food = x[0] == "item" and ent[x].get("type") in ("Consumable", "Material", "Misc")
        if k == "piece" and (k, i) in ent and not (i in COOKING and food) and (k, i) not in sel:  # bait: the
            # preparation table
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
dpar, dkids = par, kids
anc_memo = {}


def anc(x):
    if x not in anc_memo:
        anc_memo[x] = set().union(*[{q} | anc(q) for q in par[x]]) if par[x] else set()
    return anc_memo[x]


# top gear: per stage, the strongest crafted weapon of each skill, the best armour piece per slot and shield
def power(i):
    if i["type"] in ARMOR:
        return i.get("armor", 0)
    if i["type"] == "Shield":
        return i.get("block", 0)
    return sum(v for k, v in i.get("damages", {}).items() if k not in IGNORED_DAMAGE)


best = {}
for x in sel:
    e = ent[x]
    if x[0] != "item" or e["via"].get("how") not in ("craft", "process") or e["type"] in ("Ammo", "AmmoNonEquipable"):
        continue
    slot = e["type"] if e["type"] in ARMOR + ["Shield"] else e.get("skill") if e.get("skill") in GEAR_SKILLS else None
    if slot and power(e) > 0:
        key = (e["stage"], slot)
        if key not in best or power(e) > power(ent[best[key]]):
            best[key] = x
gear = set(best.values())
print(len(lonely), "lonely dropped:", " ".join(f"{x[1]}({ent[x].get('type', x[0])}:{ent[x].get('via', {}).get('how')})" for x in sorted(lonely)), file=sys.stderr)
print(collections.Counter(x[0] for x in sel), file=sys.stderr)
counts = collections.Counter(ent[x]["stage"] for x in ent if x[0] in ("item", "piece"))
print(len(sel), "nodes", sum(len(p) for p in par.values()), "edges", sum(len(p) for p in dpar.values()), "drawn",
      [sum(1 for x in sel if stage(x) == i) for i in range(len(S))], "gear", len(gear), file=sys.stderr)

# --- layout: a band per stage; rows by longest path inside it; top gear, then the boss, last ---
W, ROWH, BANDPAD, MAXROW, MARGIN = 1000, 104, 64, 10, 50
GATE = GEAR = 1000
BOSS = GEAR + 1  # the boss is the last thing done in a tier
rank = {}
for x in sorted(sel, key=lambda x: (stage(x), len(anc(x)))):
    if x in bosses:
        rank[x] = BOSS
    elif x in gear:
        rank[x] = GEAR
    else:
        rank[x] = max([rank[p] + 1 for p in dpar[x] if stage(p) == stage(x) and rank.get(p, GATE) < GATE], default=0)
for si in range(len(S)):  # as late as possible: a node with no parent in its tier sits just above its first user
    last = max([rank[x] for x in sel if stage(x) == si and rank[x] < GATE], default=0)
    r = lambda k: last + 1 if rank[k] >= GATE else rank[k]
    for x in sorted((x for x in sel if stage(x) == si and rank[x] < GATE), key=lambda x: -rank[x]):
        if not any(stage(p) == si for p in dpar[x]):
            users = [r(k) for k in dkids[x] if stage(k) == si]
            if users:
                rank[x] = max(rank[x], min(users) - 1)
rows, ypos, bands, y = [], {}, [], 0
for si, s in enumerate(S):
    members = [x for x in sel if stage(x) == si]
    top = y
    y += BANDPAD
    byrank = collections.defaultdict(list)
    for x in members:
        byrank[rank[x]].append(x)
    for r in sorted(byrank):
        row = sorted(byrank[r], key=lambda x: ent[x].get("name", ""))
        n = -(-len(row) // MAXROW)  # split evenly over as few rows as fit
        for k in range(n):
            chunk = row[k::n]
            rows.append(chunk)
            for x in chunk:
                ypos[x] = y + 24
            y += ROWH
    y += 12
    bands.append((s, top, y, counts[s], len(members)))
H = y + 20


def spread(n):
    """n evenly spaced x positions across the shaft."""
    return [MARGIN + (W - 2 * MARGIN) * (i + .5) / n for i in range(n)]


xpos = {}
for row in rows:
    for x, p in zip(row, spread(len(row))):
        xpos[x] = p
for it in range(16):  # crossing reduction: order each row by its neighbours' mean x, then spread it evenly
    for row in (rows if it % 2 == 0 else rows[::-1]):
        nbrs = lambda x: (dpar[x] if it % 2 == 0 else dkids[x]) | (dpar[x] | dkids[x] if it >= 10 else set())
        want = {x: sum(xpos[n] for n in nbrs(x)) / len(nbrs(x)) if nbrs(x) else xpos[x] for x in row}
        row.sort(key=lambda x: want[x])
        for x, p in zip(row, spread(len(row))):
            xpos[x] = p

e = html.escape
nid = lambda x: f"{x[0]}:{x[1]}"


def label(name, width):
    """One or two lines that fit the node's slot."""
    chars = max(8, int(width / 6.4))
    if len(name) <= chars:
        return f'<text y="36">{e(name)}</text>'
    words, a = name.split(), ""
    while words and len(a + " " + words[0]) <= chars + 1:
        a = (a + " " + words.pop(0)).strip()
    b = " ".join(words)
    if not a:
        a, b = name[:chars - 1] + "…", ""
    b = b if len(b) <= chars else b[:chars - 1] + "…"
    return f'<text y="36">{e(a)}</text>' + (f'<text y="50">{e(b)}</text>' if b else "")


svg = [f'<svg viewBox="0 0 {W} {H}" class="well" role="img" aria-label="Tech tree, by progression stage"><defs>']
pairs = {(ent[p]["stage"], ent[x]["stage"]) for x in sel for p in dpar[x]}
for a, b in pairs:
    svg.append(f'<linearGradient id="g-{a}-{b}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{COL[a]}"/>'
               f'<stop offset="1" stop-color="{COL[b]}"/></linearGradient>')
svg.append("</defs>")
for i, (s, top, bot, n_all, n_shown) in enumerate(bands):
    svg.append(f'<g class="band" style="--tier:{COL[s]}"><line x1="{MARGIN / 2}" x2="{W - MARGIN / 2}" y1="{top + 8}" '
               f'y2="{top + 8}"/><text x="{MARGIN / 2}" y="{top + 34}" class="bandname">{e(NAMES.get(s, s))}</text>'
               f'<a href="items/index.html"><text x="{W - MARGIN / 2}" y="{top + 34}" class="bandmore" '
               f'text-anchor="end">{n_shown} of {n_all} →</text></a></g>')
for x in sel:
    for p in dpar[x]:
        x1, y1, x2, y2 = xpos[p], ypos[p] + (52 if len(ent[p].get("name", "")) > 12 else 40), xpos[x], ypos[x] - 22
        x2 += .5 if abs(x2 - x1) < .5 else 0  # a gradient needs a box with width
        d = (y2 - y1) * 0.5
        svg.append(f'<path class="edge" stroke="url(#g-{ent[p]["stage"]}-{ent[x]["stage"]})" data-a="{e(nid(p))}" '
                   f'data-b="{e(nid(x))}" d="M{x1:.1f},{y1:.0f} C{x1:.1f},{y1 + d:.0f} {x2:.1f},{y2 - d:.0f} {x2:.1f},{y2:.0f}"/>')
for row in rows:
    slot = (W - 2 * MARGIN) / len(row)
    for x in row:
        s = ent[x]["stage"]
        ic = ent[x].get("icon") if x[0] != "creature" else next(
            (items[d["item"]].get("icon") for d in ent[x].get("drops", []) if items.get(d["item"], {}).get("type") == "Trophy"), None)
        href = f'{ {"item": "items", "piece": "pieces", "creature": "creatures"}[x[0]]}/{x[1]}.html'
        name = ent[x].get("name", x[1])
        cls = "node" + (" boss" if x in bosses else " gear" if x in gear else "")
        img = f'<image href="icons/{ic}.png" x="-16" y="-16" width="32" height="32"/>' if ic in ICONS else ""
        svg.append(f'<a href="{href}" class="{cls}" data-id="{e(nid(x))}" style="--tier:{COL[s]}" '
                   f'transform="translate({xpos[x]:.1f},{ypos[x]})"><title>{e(name)}</title>'
                   f'<rect x="-22" y="-22" width="44" height="44" rx="8"/>{img}{label(name, min(slot, 120))}</a>')
svg.append("</svg>")

par_ids = {nid(x): [nid(p) for p in par[x]] for x in sel}
css = open(ROOT / "site/style.css").read()
page = f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Tech well (prototype)</title><style>{css}
.wellbox{{background:#121417;border-radius:10px;padding:8px 0;margin-top:12px}}
.well{{width:100%;height:auto;display:block;font-family:system-ui,-apple-system,"Segoe UI",sans-serif}}
.band line{{stroke:var(--tier);stroke-opacity:.35}}
.bandname{{fill:var(--tier);font-size:18px;font-weight:700;letter-spacing:.04em}}
.bandmore{{fill:#9a9387;font-size:13px}}
.edge{{fill:none;stroke-width:1.5;stroke-opacity:.55;transition:stroke-opacity .15s}}
.node rect{{fill:#1d2024;stroke:var(--tier);stroke-width:1.5}}
.node.gear rect{{stroke-width:2.5}}
.node.boss rect{{fill:#2a1f14;stroke:#e0a24a;stroke-width:2.5}}
.node text{{fill:var(--tier);font-size:11.5px;text-anchor:middle}}
.node:hover text{{text-decoration:underline}}
.well.focus .edge{{stroke-opacity:.07}} .well.focus .node{{opacity:.3}}
.well.focus .edge.on{{stroke-opacity:1;stroke-width:2.4}} .well.focus .node.on{{opacity:1}}
</style></head><body><main><h1>Tech tree</h1><p class="sub">Prototype: every obtainable item but food and meads, the bosses, the stations
they need ({len(sel)} nodes). Hover to trace a path.</p>
<div class="wellbox">{''.join(svg)}</div></main>
<script>
const P={json.dumps(par_ids)},K={{}};for(const[k,v]of Object.entries(P))for(const p of v)(K[p]=K[p]||[]).push(k);
const svg=document.querySelector('.well');
function walk(id,m,s){{for(const n of m[id]||[])if(!s.has(n)){{s.add(n);walk(n,m,s)}}return s}}
svg.addEventListener('mouseover',ev=>{{const a=ev.target.closest('.node');if(!a)return;const id=a.dataset.id;
 const on=new Set([id,...walk(id,P,new Set()),...walk(id,K,new Set())]);svg.classList.add('focus');
 svg.querySelectorAll('.node').forEach(n=>n.classList.toggle('on',on.has(n.dataset.id)));
 svg.querySelectorAll('.edge').forEach(n=>n.classList.toggle('on',on.has(n.dataset.a)&&on.has(n.dataset.b)))}});
svg.addEventListener('mouseleave',()=>svg.classList.remove('focus'));
</script></body></html>"""
OUT.write_text(page)
print(OUT, file=sys.stderr)

# --- audit: needs left out of the graph, and roots by how they're got ---
if "--audit" in sys.argv:
    miss = collections.Counter()
    ex = collections.defaultdict(list)
    for x in sel:
        for k, i, _ in way_needs(x):
            n = boss_of((k, i)) if k == "creature" else (k, i)
            if n in sel:
                continue
            why = ("cooking piece" if k == "piece" and i in COOKING else "creature" if k == "creature" else
                   "consumable" if ent.get(n, {}).get("type") == "Consumable" else "cooked item" if n in ent and cooked(n)
                   else "unstaged/unknown" if n not in ent else "OTHER")
            miss[why] += 1
            ex[why].append(f"{x[1]}<-{i}")
    print("left-out needs:", dict(miss), file=sys.stderr)
    for w in ("OTHER", "unstaged/unknown", "cooked item", "consumable", "cooking piece"):
        if ex[w]:
            print(" ", w, ex[w][:15], file=sys.stderr)
    roots = collections.defaultdict(list)
    for x in sel:
        if not par[x]:
            v = ent[x].get("via", {})
            sd = srcs.get(v.get("from"), {})
            roots[f'{x[0]} {v.get("how")}{"/" + sd["kind"] if sd else ""}'].append(x[1])
    for k, v in sorted(roots.items(), key=lambda kv: -len(kv[1])):
        print(f"  root {k}: {len(v)}", v[:10], file=sys.stderr)
