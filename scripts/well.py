"""Prototype (#25): the 'well' tech tree. Reads data/, writes .cache/site/public/well.html (uses the built site's icons;
run `make site` first, then `python3 scripts/well.py [--audit]` and open http://localhost:8000/well.html)."""
import json, collections, html, math, sys
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


# 1-2: every obtainable item but consumables, trophies and what cooking stations make (food and mead intermediates)
cooked = lambda x: any(k == "piece" and i in COOKING for k, i, _ in way_needs(x))
# ...and fishing: fish, bait, the rod and the hat made of fish lead nowhere else (their catch drops and the trophies
# only bait needs then connect to nothing and are dropped)
FISHING = {"FishingRod", "HelmetFishingHat"} | {i for s in srcs.values() if s["kind"] == "fishing"
                                                for i in [s["id"]] + [b["item"] for b in s.get("baits", [])]}
sel = {x for x, e in ent.items() if x[0] == "item" and e.get("type") not in ("Consumable", "Trophy") and not cooked(x)
       and x[1] not in FISHING}
# 3: bosses (their drops are items already)
sel |= bosses
# ...but keep a consumable, trophy or cooked item something kept needs (Blueberries for Berserker armour, the Deer
# trophy for Eikthyr's altar), and 4: the non-cooking pieces they need; one fixed point, so an item only a piece needs
# is kept too (the Asksvin trophy for the Galdr table's upgrade)
todo = list(sel)
while todo:
    x = todo.pop()
    for k, i, _ in way_needs(x):
        if (k, i) not in ent or (k, i) in sel:
            continue
        food = x[0] == "item" and ent[x].get("type") in ("Consumable", "Material", "Misc")
        if k == "item" and i not in FISHING or k == "piece" and not (i in COOKING and food):
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

# --- layout: the well is a cylinder seen from slightly above. Each stage is a band of the same height; inside it a ring
# per rank (longest path inside the stage; top gear, then the boss, last). Round each ring the most important nodes
# face the viewer: importance = how many nodes need it, directly or not. Depth shows as size, brightness and fog.
W, BANDPAD, ROWH, R, TILT, NMIN, BETA, SAMPLES = 1200, 60, 76, 440, 44, 18, 1.5, 12
CX, TOP = W / 2, TILT + 24
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
desc_memo = {}


def desc(x):
    if x not in desc_memo:
        desc_memo[x] = set().union(*[{k} | desc(k) for k in dkids[x]]) if dkids[x] else set()
    return desc_memo[x]


imp = {x: len(desc(x)) for x in sel}
byrank = collections.defaultdict(lambda: collections.defaultdict(list))
for x in sel:
    byrank[stage(x)][rank[x]].append(x)
BANDH = BANDPAD + ROWH * max(len(v) for v in byrank.values())  # every stage the same height
rings, ypos, bands = [], {}, []
for si, s in enumerate(S):
    top = TOP + si * BANDH
    ranks = sorted(byrank[si])
    for j, rk in enumerate(ranks):  # the stage's rings spread evenly over its band
        rings.append(byrank[si][rk])
        for x in byrank[si][rk]:
            ypos[x] = top + BANDPAD + (BANDH - BANDPAD) * (j + .5) / len(ranks)
    bands.append((s, top, counts[s], sum(len(v) for v in byrank[si].values())))
H = TOP + len(S) * BANDH + TILT + 24

# angles: a ring's nodes take evenly spaced slots on an arc centred on the front (the whole circle once it is full);
# each pass, a node wants the angle where its neighbours are, pulled to the front by importance (log share of the
# stage's most important node), and takes the free slot nearest it, the most important first
wrap = lambda a: (a + math.pi) % math.tau - math.pi
slots = lambda n: [(j - (n - 1) / 2) * math.tau / max(n, NMIN) for j in range(n)]
nb = {x: dpar[x] | dkids[x] for x in sel}
top_imp = collections.defaultdict(int)
for x in sel:
    top_imp[stage(x)] = max(top_imp[stage(x)], imp[x])
front = {x: math.log1p(imp[x]) / math.log1p(top_imp[stage(x)]) if top_imp[stage(x)] else 0 for x in sel}
theta = {}
for ring in rings:  # start: by importance, the most important in the middle, the rest to alternate sides
    order = sorted(ring, key=lambda x: (-imp[x], ent[x].get("name", "")))
    ring[:] = order[1::2][::-1] + order[0::2]
    theta.update(zip(ring, slots(len(ring))))
for it in range(24):
    for ring in (rings if it % 2 == 0 else rings[::-1]):
        want = {x: math.atan2(sum(math.sin(theta[n]) for n in nb[x]),
                              sum(math.cos(theta[n]) for n in nb[x]) + BETA * front[x] * max(1, len(nb[x])))
                for x in ring}
        free = slots(len(ring))
        for x in sorted(ring, key=lambda x: (-imp[x], ent[x].get("name", ""))):  # the most important choose first
            theta[x] = min(free, key=lambda a: abs(wrap(a - want[x])))
            free.remove(theta[x])


# --- page: nodes are links placed by CSS from their angle (the first render, and without JavaScript); turning the
# well sets each visible node's transform from JavaScript instead (CSS trig on every node costs ~4x more per frame).
# Edges and rings are drawn on two screen-sized canvases, behind and in front of the fog
e = html.escape
order = [x for ring in rings for x in ring]
idx = {x: n for n, x in enumerate(order)}
nodes = []
for ring in rings:
    k = math.tau / max(len(ring), NMIN)  # slot width per unit of radius
    for x in ring:
        ic = ent[x].get("icon") if x[0] != "creature" else next(
            (items[dd["item"]].get("icon") for dd in ent[x].get("drops", []) if items.get(dd["item"], {}).get("type") == "Trophy"), None)
        href = f'{ {"item": "items", "piece": "pieces", "creature": "creatures"}[x[0]]}/{x[1]}.html'
        name = ent[x].get("name", x[1])
        cls = "node" + (" boss" if x in bosses else " gear" if x in gear else "")
        img = f'<img src="icons/{ic}.png" alt="" loading="lazy" draggable="false">' if ic in ICONS else ""
        nodes.append(f'<a href="{href}" class="{cls}" data-n="{idx[x]}" draggable="false" title="{e(name)}" '
                     f'style="--a:{theta[x]:.4f}rad;--k:{k:.4f};top:{ypos[x]:.0f}px;--tier:{COL[ent[x]["stage"]]}">'
                     f'<span class="ic">{img}</span><span class="lb">{e(name)}</span></a>')
labels = "".join(f'<div class="bandname" style="top:{top + 12:.0f}px;--tier:{COL[s]}">{e(NAMES.get(s, s))} '
                 f'<a href="items/index.html">{n_shown} of {n_all} →</a></div>' for s, top, n_all, n_shown in bands)
fog = ",".join(f"rgba(18,20,23,{.62 * math.sqrt(max(0, 1 - u * u)):.3f}) {(u + 1) * 50:.0f}%" for u in [k / 10 - 1 for k in range(21)])
data = {"a": [round(theta[x], 4) for x in order], "y": [round(ypos[x]) for x in order], "c": [stage(x) for x in order], "k": [round(math.tau / max(len(r), NMIN), 4) for r in rings for _ in r],
        "col": [COL[s] for s in S], "bands": [round(top) for _, top, _, _ in bands] + [round(TOP + len(S) * BANDH)],
        "par": [sorted(idx[p] for p in par[x]) for x in order]}
css = open(ROOT / "site/style.css").read()
page = f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Tech well (prototype)</title><style>{css}
.well{{position:relative;height:{H:.0f}px;margin-top:12px;background:#121417;border-radius:10px;overflow:clip;
 touch-action:pan-y;user-select:none;-webkit-user-select:none;--rot:0rad;--R:348;--tilt:44;
 font-family:system-ui,-apple-system,"Segoe UI",sans-serif}}
.well canvas{{position:sticky;top:0;display:block;width:100%;height:100vh;margin-bottom:-100vh;pointer-events:none}}
.well .back{{z-index:0}} .well .front{{z-index:100}}
.fog{{position:absolute;top:0;bottom:0;left:calc(50% - var(--R) * 1px);width:calc(var(--R) * 2px);z-index:100;
 pointer-events:none;background:linear-gradient(to right,{fog})}}
.node{{--t:calc(var(--a) + var(--rot));--w:min(130, var(--R) * var(--k));--d:calc((cos(var(--t)) + 1) / 2);
 position:absolute;left:50%;width:calc(var(--w) * 1px);margin:-22px 0 0 calc(var(--w) * -.5px);
 display:flex;flex-direction:column;align-items:center;text-decoration:none;transform-origin:50% 22px;
 transform:translate(calc(var(--R) * sin(var(--t)) * 1px), calc(var(--tilt) * cos(var(--t)) * 1px)) scale(calc(.55 + .45 * var(--d)));
 opacity:calc(.35 + .65 * var(--d));z-index:calc(100 + 99 * cos(var(--t)));-webkit-user-drag:none}}
.node .ic{{width:44px;height:44px;box-sizing:border-box;border:1.5px solid var(--tier);border-radius:8px;background:#1d2024;
 display:flex;align-items:center;justify-content:center}}
.node img{{width:32px;height:32px}}
.node.gear .ic{{border-width:2.5px}} .node.boss .ic{{background:#2a1f14;border:2.5px solid #e0a24a}}
.node .lb{{color:var(--tier);font-size:11.5px;line-height:13px;text-align:center;margin-top:4px;max-width:100%;
 display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;
 opacity:clamp(0, (cos(var(--t)) * var(--R) * var(--k) - 64) / 8, 1)}}
.node:hover .lb{{text-decoration:underline}}
.bandname{{position:absolute;left:12px;z-index:300;color:var(--tier);font-size:18px;font-weight:700;letter-spacing:.04em;
 pointer-events:none}}
.bandname a{{pointer-events:auto;color:#9a9387;font-size:13px;font-weight:400;letter-spacing:0;margin-left:6px}}
.well.focus .node{{opacity:.15 !important}} .well.focus .node.on{{opacity:1 !important}} .well.focus .node.on .lb{{opacity:1 !important}}
.well.dragging .node{{pointer-events:none}}
</style></head><body><main><h1>Tech tree</h1><p class="sub">Prototype: every obtainable item but food and meads, the bosses, the stations
they need ({len(sel)} nodes). Drag sideways to turn the well; hover (or tap) to trace a path.</p>
<div class="well"><canvas class="back"></canvas><div class="fog"></div><canvas class="front"></canvas>{labels}{''.join(nodes)}</div></main>
<script>
const D={json.dumps(data, separators=(",", ":"))};
const well=document.querySelector('.well'),cv=[...well.querySelectorAll('canvas')],cx=cv.map(c=>c.getContext('2d'));
const nodes=[...well.querySelectorAll('.node')].sort((a,b)=>a.dataset.n-b.dataset.n),lbs=nodes.map(a=>a.querySelector('.lb')),N=D.a.length,seen=new Float64Array(N).fill(NaN),KID=D.a.map(()=>[]),EDGES=[];
D.par.forEach((ps,c)=>ps.forEach(p=>{{KID[p].push(c);EDGES.push([p,c])}}));
let rot=0,R=348,TILT=44,W=0,dpr=1,on=null,up=null,down=null,queued=false;
function walk(n,m,s){{for(const q of m[n])if(!s.has(q)){{s.add(q);walk(q,m,s)}}return s}}
function size(){{W=well.clientWidth;R=W<600?W*.75:Math.min(440,W*.37);TILT=R/10;dpr=devicePixelRatio||1;
 well.style.setProperty('--R',R.toFixed(1));well.style.setProperty('--tilt',TILT.toFixed(1));seen.fill(NaN);
 for(const c of cv){{c.width=Math.round(c.clientWidth*dpr);c.height=Math.round(c.clientHeight*dpr)}}draw()}}
function place(off,vh){{  // the nodes in view (and a screen either side) that haven't been placed at this rotation
 for(let n=0;n<N;n++){{if(seen[n]===rot||D.y[n]<off-vh||D.y[n]>off+2*vh)continue;seen[n]=rot;
  const t=D.a[n]+rot,c=Math.cos(t),d=(c+1)/2,s=nodes[n].style;
  s.transform=`translate(${{(R*Math.sin(t)).toFixed(1)}}px,${{(TILT*c).toFixed(1)}}px) scale(${{(.55+.45*d).toFixed(3)}})`;
  s.opacity=(.35+.65*d).toFixed(3);s.zIndex=Math.round(100+99*c);s.pointerEvents=c<0?'none':'';  // behind the fog: not a target
  lbs[n].style.opacity=Math.min(1,Math.max(0,(c*R*D.k[n]-64)/8)).toFixed(2)}}}}
function draw(){{queued=false;
 const off=cv[0].getBoundingClientRect().top-well.getBoundingClientRect().top,vh=cv[0].clientHeight,mid=W/2;place(off,vh);
 for(const g of cx){{g.setTransform(dpr,0,0,dpr,0,-off*dpr);g.clearRect(0,off,W,vh)}}
 for(const[i,y]of D.bands.entries()){{if(y<off-TILT-10||y>off+vh+TILT+10)continue;  // rings: back half, front half
  for(const f of[0,1]){{const g=cx[f];g.strokeStyle=D.col[Math.min(i,D.col.length-1)];g.globalAlpha=f?.35:.2;g.lineWidth=1;
   g.beginPath();g.ellipse(mid,y,R,TILT,0,f?0:Math.PI,f?Math.PI:2*Math.PI);g.stroke()}}}}
 const lit=[];
 for(const ed of EDGES){{const[p,c]=ed,y0=D.y[p]+22,y1=D.y[c]-22;
  if(Math.max(y0,y1)<off-TILT||Math.min(y0,y1)>off+vh+TILT)continue;
  const hot=on&&(up.has(p)&&up.has(c)||down.has(p)&&down.has(c));/* on a path through it */if(hot){{lit.push(ed);continue}}edge(p,c,y0,y1,false)}}
 for(const[p,c]of lit)edge(p,c,D.y[p]+22,D.y[c]-22,true)}}
function edge(p,c,y0,y1,hot){{  // along the cylinder's surface, a stroke per run on one side
 const a0=D.a[p]+rot,da=((D.a[c]-D.a[p]+Math.PI)%(2*Math.PI)+2*Math.PI)%(2*Math.PI)-Math.PI,S=12,pts=[];
 for(let k=0;k<=S;k++){{const t=k/S,a=a0+da*t,y=y0+(y1-y0)*(3*t*t-2*t*t*t);
  pts.push([W/2+R*Math.sin(a),y+TILT*Math.cos(a),Math.cos(a)])}}
 let s=0;for(let k=1;k<=S;k++)if(k==S||(pts[k+1][2]>=0)!=(pts[k][2]>=0)){{
  const run=pts.slice(s,k+1),d=run.reduce((m,q)=>m+q[2],0)/run.length,g=cx[d>=0?1:0],dd=(d+1)/2;
  g.globalAlpha=hot?1:on?.04:.04+.26*dd*dd;g.lineWidth=hot?2.4:1.2;
  if(D.c[p]==D.c[c])g.strokeStyle=D.col[D.c[c]];
  else{{const gr=g.createLinearGradient(0,y0,0,y1);gr.addColorStop(0,D.col[D.c[p]]);gr.addColorStop(1,D.col[D.c[c]]);g.strokeStyle=gr}}
  g.beginPath();g.moveTo(run[0][0],run[0][1]);for(const q of run.slice(1))g.lineTo(q[0],q[1]);g.stroke();s=k}}}}
function later(){{if(!queued){{queued=true;requestAnimationFrame(draw)}}}}
function focus(n){{up=n==null?null:walk(n,D.par,new Set([n]));down=n==null?null:walk(n,KID,new Set([n]));
 on=n==null?null:new Set([...up,...down]);
 well.classList.toggle('focus',!!on);for(const a of nodes)a.classList.toggle('on',!!on&&on.has(+a.dataset.n));later()}}
// turning: horizontal drags (vertical ones scroll the page), then it coasts
let drag=null,moved=false,vel=0,touch=false;
well.addEventListener('pointerdown',ev=>{{touch=ev.pointerType!='mouse';drag={{x:ev.clientX,t:ev.timeStamp}};moved=false;vel=0}});
well.addEventListener('pointermove',ev=>{{if(!drag)return;const dx=ev.clientX-drag.x;
 if(!moved){{if(Math.abs(dx)<6)return;moved=true;well.setPointerCapture(ev.pointerId);well.classList.add('dragging')}}
 rot+=dx/R;vel=dx/R/Math.max(8,ev.timeStamp-drag.t);drag={{x:ev.clientX,t:ev.timeStamp}};later()}});
function release(){{if(!drag)return;drag=null;well.classList.remove('dragging');
 if(moved){{let last=performance.now();(function coast(now){{vel*=Math.pow(.995,now-last);rot+=vel*(now-last);last=now;draw();
  if(Math.abs(vel)>2e-5&&!drag)requestAnimationFrame(coast)}})(last)}}}}
well.addEventListener('pointerup',release);well.addEventListener('pointercancel',()=>{{drag=null;well.classList.remove('dragging')}});
well.addEventListener('click',ev=>{{if(moved){{ev.preventDefault();moved=false;return}}
 const a=ev.target.closest('.node');
 if(a&&touch&&!(on&&on.has(+a.dataset.n)&&a.classList.contains('tapped'))){{  // touch: tap traces, a second tap opens
  ev.preventDefault();nodes.forEach(n=>n.classList.remove('tapped'));a.classList.add('tapped');focus(+a.dataset.n)}}
 else if(!a)focus(null)}});
well.addEventListener('pointerover',ev=>{{const a=ev.target.closest('.node');if(ev.pointerType=='mouse'&&a&&!drag)focus(+a.dataset.n)}});
well.addEventListener('pointerleave',ev=>{{if(ev.pointerType=='mouse')focus(null)}});
addEventListener('scroll',later,{{passive:true}});addEventListener('resize',size);size();
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
