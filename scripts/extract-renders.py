#!/usr/bin/env python3
"""Render every dumped location as a textured isometric image, straight from the server's asset bundles (#52).

Locations are soft-referenced prefabs in StreamingAssets/SoftRef/Bundles; their meshes, materials and textures sit
in other bundles (loaded transitively through each file's externals) or in Unity's built-in resources (the LOD1 roof
boxes are built-in Cubes). Shaders aren't in the server data, so materials are drawn from `_MainTex` x `_Color` with
a fixed light, a z-buffer and alpha cutout; refraction materials (trader force fields) are drawn as faint glass.

    scripts/extract-renders.py <server_dir> <raw_dump_dir> <out_dir> [location ...]

Writes <out_dir>/<location>.webp (transparent background) for each location with static meshes. Locations whose
buildings come from a DungeonGenerator (camps, villages) or that hold only a creature render nothing. Needs UnityPy
and numpy (see requirements.txt; scripts/renders.sh sets up the venv).
"""
import json
import math
import os
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import UnityPy
from PIL import Image

SIZE, SS = 800, 2                       # output px, supersampling factor
LOD = 1                                 # LODGroup level: the game's distance view, simpler and closer to how players spot it
YAW, PITCH = math.radians(45), math.radians(30)
LIGHT = np.array([0.35, 0.85, 0.4]) / np.linalg.norm([0.35, 0.85, 0.4])
GLASS = np.array([0.75, 0.88, 1.0])     # colour of refraction (force field) surfaces
RENDER_COMPONENTS = {"Transform", "RectTransform", "LODGroup", "MeshFilter", "MeshRenderer"}


def index(bundles: Path):
    """CAB name -> bundle file, location prefab name -> bundle file, bundle file -> referenced CABs."""
    cab2b, prefab2b, ext = {}, {}, {}
    for b in sorted(bundles.iterdir()):
        e = UnityPy.load(str(b))
        for name, f in e.file.files.items():
            cab2b[name] = b.name
            ext.setdefault(b.name, []).extend(x.path.split("/")[-1] for x in getattr(f, "externals", []))
        for o in e.objects:
            if o.type.name == "AssetBundle":
                for k, _ in o.read().m_Container:
                    if k.endswith(".prefab"):
                        prefab2b[Path(k).stem] = b.name
    return cab2b, prefab2b, ext


def deps(start, cab2b, ext):
    seen, todo = set(), [start]
    while todo:
        n = todo.pop()
        if n not in seen:
            seen.add(n)
            todo += [cab2b[c] for c in ext.get(n, []) if c in cab2b]
    return sorted(seen)


def qrot(q, v):
    """Rotate (N,3) points by a Unity quaternion."""
    u = np.array([q.x, q.y, q.z])
    t = 2 * np.cross(u, v)
    return v + q.w * t + np.cross(u, t)


def obj_key(pptr):
    """Cache key for a referenced object (m_FileID is relative to the referencing file)."""
    try:
        r = pptr.deref()
        return r.assets_file.name, r.path_id
    except Exception:
        return None, id(pptr)


class Scene:
    def __init__(self):
        self.meshes, self.mats = {}, {}
        self.parts = []  # (world verts (n,3), uv (n,2), faces (m,3), material)

    @staticmethod
    def components(g):
        out = {}
        for c in g.m_Components:
            r = getattr(c, "component", c).deref()
            t = r.type.name
            if t in RENDER_COMPONENTS:
                o = r.parse_as_object()
                o._pid = r.path_id
                out["Transform" if t == "RectTransform" else t] = o
        return out

    def mesh(self, pptr):
        key = obj_key(pptr)
        if key not in self.meshes:
            v, vt, subs = [], [], []
            try:
                obj = pptr.read().export()
            except Exception as e:
                print(f"  mesh {pptr.m_PathID}: {type(e).__name__} {str(e)[:80]}", file=sys.stderr)
                obj = ""
            for line in obj.splitlines():
                if line.startswith("v "):
                    x, y, z = map(float, line[2:].split()[:3])
                    v.append((-x, y, z))  # export mirrors x
                elif line.startswith("vt "):
                    vt.append(tuple(map(float, line[3:].split()[:2])))
                elif line.startswith("g "):
                    subs.append([])
                elif line.startswith("f "):
                    if not subs:
                        subs.append([])
                    subs[-1].append([int(p.split("/")[0]) - 1 for p in line[2:].split()[:3]])
            v = np.array(v, float).reshape(-1, 3)
            vt = np.array(vt, float).reshape(-1, 2) if len(vt) == len(v) else np.zeros((len(v), 2))
            self.meshes[key] = (v, vt, [np.array(s, int).reshape(-1, 3) for s in subs])
        return self.meshes[key]

    def material(self, pptr):
        key = obj_key(pptr)
        if key in self.mats:
            return self.mats[key]
        m = {"name": "", "tex": None, "tint": np.ones(3), "st": (1, 1, 0, 0), "cutoff": None, "glass": False}
        try:
            mat = pptr.read()
            m["name"] = mat.m_Name
            props = mat.m_SavedProperties
            floats, colors = dict(props.m_Floats), dict(props.m_Colors)
            if "_Color" in colors:
                c = colors["_Color"]
                m["tint"] = np.array([c.r, c.g, c.b])
            m["glass"] = "_RefractionIntensity" in floats
            for k, t in props.m_TexEnvs:
                if k == "_MainTex" and t.m_Texture.m_PathID:
                    try:
                        m["tex"] = np.asarray(t.m_Texture.read().image.convert("RGBA"), np.float32) / 255
                        m["st"] = (t.m_Scale.x, t.m_Scale.y, t.m_Offset.x, t.m_Offset.y)
                    except Exception:
                        pass
            if floats.get("_Cutoff", 0) > 0 and m["tex"] is not None and m["tex"][..., 3].min() < 0.5:
                m["cutoff"] = floats["_Cutoff"]
        except Exception:
            pass
        self.mats[key] = m
        return m

    def walk(self, g, chain=None, skip=None):
        """Collect the active renderers under g; the root's own transform is the location origin."""
        skip = set() if skip is None else skip
        if not g.m_IsActive:
            return
        cs = self.components(g)
        tr = cs["Transform"]
        chain = [] if chain is None else chain + [tr]
        if "LODGroup" in cs:
            lods = cs["LODGroup"].m_LODs
            keep = {r.renderer.m_PathID for r in lods[min(LOD, len(lods) - 1)].renderers}
            skip.update(r.renderer.m_PathID for lod in lods for r in lod.renderers if r.renderer.m_PathID not in keep)
        mf, mr = cs.get("MeshFilter"), cs.get("MeshRenderer")
        if mf and mr and mr.m_Enabled and mr._pid not in skip and mf.m_Mesh.m_PathID:
            v, vt, subs = self.mesh(mf.m_Mesh)
            mats = list(mr.m_Materials)
            if len(v) and mats:
                w = v
                for t in reversed(chain):
                    s, p = t.m_LocalScale, t.m_LocalPosition
                    w = qrot(t.m_LocalRotation, w * [s.x, s.y, s.z]) + [p.x, p.y, p.z]
                for i, f in enumerate(subs):
                    if len(f):
                        self.parts.append((w, vt, f, self.material(mats[min(i, len(mats) - 1)])))
        for ch in tr.m_Children:
            self.walk(ch.read().m_GameObject.read(), chain, skip)


def sample(m, uv):
    if m["tex"] is None:
        return np.broadcast_to(np.array([0.6, 0.6, 0.6, 1.0]), (len(uv), 4))
    tex = m["tex"]
    h, w = tex.shape[:2]
    sx, sy, ox, oy = m["st"]
    u, v = (uv[:, 0] * sx + ox) % 1.0, (uv[:, 1] * sy + oy) % 1.0
    return tex[np.minimum(((1 - v) * h).astype(int), h - 1), np.minimum((u * w).astype(int), w - 1)]


def triangles(s, f, R):
    """Yield (face index, pixel xs, ys, barycentrics (k,3)) for each triangle's covered pixels."""
    for fi, tri in enumerate(f):
        a, b, c = s[tri]
        x0, y0 = np.maximum(np.floor(np.minimum(np.minimum(a, b), c)).astype(int), 0)
        x1, y1 = np.minimum(np.ceil(np.maximum(np.maximum(a, b), c)).astype(int), R - 1)
        if x1 < x0 or y1 < y0:
            continue
        den = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        if abs(den) < 1e-9:
            continue
        ys, xs = np.mgrid[y0:y1 + 1, x0:x1 + 1]
        px, py = xs.ravel() + 0.5, ys.ravel() + 0.5
        l0 = ((b[1] - c[1]) * (px - c[0]) + (c[0] - b[0]) * (py - c[1])) / den
        l1 = ((c[1] - a[1]) * (px - c[0]) + (a[0] - c[0]) * (py - c[1])) / den
        l2 = 1 - l0 - l1
        ins = (l0 >= 0) & (l1 >= 0) & (l2 >= 0)
        if ins.any():
            yield fi, px[ins].astype(int), py[ins].astype(int), np.stack([l0[ins], l1[ins], l2[ins]], 1)


def render(scene, radius):
    """Isometric z-buffer render; parts centred further than radius from the origin (or 300 m up/down) are left out."""
    cy, sy, cp, sp = math.cos(YAW), math.sin(YAW), math.cos(PITCH), math.sin(PITCH)
    parts = []
    for w, vt, f, m in scene.parts:
        c = w.mean(0)
        if abs(c[1]) > 300 or math.hypot(c[0], c[2]) > radius:
            continue
        X = w[:, 0] * cy - w[:, 2] * sy
        Z = w[:, 0] * sy + w[:, 2] * cy
        parts.append((np.stack([X, -(w[:, 1] * cp + Z * sp), -w[:, 1] * sp + Z * cp], 1), w, vt, f, m))
    if not parts:
        return None
    pts = np.concatenate([p[0][np.unique(p[3])] for p in parts])
    lo, hi = pts[:, :2].min(0), pts[:, :2].max(0)
    R = SIZE * SS
    sc = R * 0.92 / max(hi - lo)
    off = (R - (hi - lo) * sc) / 2
    zb = np.full((R, R), np.inf, np.float32)
    img = np.zeros((R, R, 4), np.float32)
    for glass_pass in (False, True):  # glass after everything opaque, blended, no depth write
        for p, w, vt, f, m in parts:
            if m["glass"] != glass_pass:
                continue
            s = (p[:, :2] - lo) * sc + off
            for fi, px, py, l in triangles(s, f, R):
                tri = f[fi]
                d = l @ p[tri, 2]
                vis = d < zb[py, px]
                if not vis.any():
                    continue
                px, py, d, l = px[vis], py[vis], d[vis], l[vis]
                if glass_pass:
                    e = np.cross(p[tri[1]] - p[tri[0]], p[tri[2]] - p[tri[0]])
                    facing = abs(e[2]) / (np.linalg.norm(e) or 1)
                    a = 0.06 + 0.5 * (1 - facing) ** 3  # fresnel-ish rim
                    img[py, px, :3] = img[py, px, :3] * (1 - a) + GLASS * a
                    img[py, px, 3] = np.maximum(img[py, px, 3], a)
                    continue
                col = sample(m, l @ vt[tri])
                if m["cutoff"] is not None:
                    keep = col[:, 3] >= m["cutoff"]
                    px, py, d, col = px[keep], py[keep], d[keep], col[keep]
                    if not len(px):
                        continue
                n = np.cross(w[tri[1]] - w[tri[0]], w[tri[2]] - w[tri[0]])
                shade = 0.5 + 0.6 * abs(float(n @ LIGHT)) / (np.linalg.norm(n) or 1)
                zb[py, px] = d
                img[py, px, :3] = np.clip(col[:, :3] * m["tint"] * shade, 0, 1)
                img[py, px, 3] = 1
    return Image.fromarray((img * 255).astype(np.uint8), "RGBA").resize((SIZE, SIZE), Image.LANCZOS)


def render_location(job):
    name, bundles, extra, raw, out = job
    t = time.time()
    try:
        env = UnityPy.load(*bundles, *extra)
        ab = next(a for a in (o.read() for o in env.objects if o.type.name == "AssetBundle")
                  if any(Path(k).stem == name for k, _ in a.m_Container))
        root = next(v.asset for k, v in ab.m_Container if Path(k).stem == name).read()
        scene = Scene()
        scene.walk(root)
        loc = json.loads((raw / "locations" / f"{name}.json").read_text())
        ext_r = next((c["fields"].get("m_exteriorRadius", 20) for c in loc["components"] if c["type"] == "Location"), 20)
        img = render(scene, max(3 * ext_r + 20, 40))
        ntri = sum(len(p[2]) for p in scene.parts)
        if img is None:
            return name, f"nothing to render ({ntri} tris)", time.time() - t
        img.save(out / f"{name}.webp", quality=85)
        return name, f"{ntri} tris", time.time() - t
    except Exception as e:
        return name, f"FAILED {type(e).__name__}: {e}", time.time() - t


def main():
    server, raw, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    data = server / "valheim_server_Data"
    bdir = data / "StreamingAssets/SoftRef/Bundles"
    out.mkdir(parents=True, exist_ok=True)
    t = time.time()
    cab2b, prefab2b, ext = index(bdir)
    print(f"indexed {len(cab2b)} bundle files in {time.time() - t:.0f} s", flush=True)
    names = sys.argv[4:] or [p.stem for p in sorted((raw / "locations").glob("*.json"))]
    extra = [str(data / "Resources/unity default resources")]
    jobs, failed = [], 0
    for n in names:
        if n not in prefab2b:
            print(f"{n}: FAILED no bundle")
            failed += 1
            continue
        jobs.append((n, [str(bdir / b) for b in deps(prefab2b[n], cab2b, ext)], extra, raw, out))
    with Pool(min(8, os.cpu_count() or 1)) as pool:
        for name, msg, dt in pool.imap_unordered(render_location, jobs):
            print(f"{name}: {msg} ({dt:.0f} s)", flush=True)
            failed += msg.startswith("FAILED")
    print(f"{len(list(out.glob('*.webp')))} renders in {time.time() - t:.0f} s")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
