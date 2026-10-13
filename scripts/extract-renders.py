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
ENTRANCE_ANGLE = math.radians(30)       # camera this far round from straight at a dungeon entrance
FRAME_FILL, FRAME_FILL_GROUND = 0.92, 0.8  # share of the frame the location fills (without / with drawn ground)
PROBE_SIZE, PROBE_MAX_TRIS = 200, 60000  # entrance-facing test renders: px, and the largest location worth it
TERRAIN_STEP = 1.0                      # m between heightmap vertices (Heightmap.m_scale)
GROUND_SLACK = 0.1                      # m below the ground still drawn (foundations meet the terrain)
GROUND = np.array([0.52, 0.49, 0.42])    # terrain colour when drawn
GLASS = np.array([0.75, 0.88, 1.0])     # colour of refraction (force field) surfaces
RENDER_COMPONENTS = {"Transform", "RectTransform", "LODGroup", "MeshFilter", "MeshRenderer"}
SKIP_SHADER_PROPS = {"_CentralFade"}    # light beam effect shader (CharredFortress beacon)
GLOSS_IN_ALPHA = "_SMOOTHNESS_TEXTURE_ALBEDO_CHANNEL_A"  # _MainTex alpha is smoothness, not transparency


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


def to_world(chain, v):
    for t in reversed(chain):
        s, p = t.m_LocalScale, t.m_LocalPosition
        v = qrot(t.m_LocalRotation, v * [s.x, s.y, s.z]) + [p.x, p.y, p.z]
    return v


class Scene:
    def __init__(self, modifiers=None, entrances=()):
        self.meshes, self.mats = {}, {}
        self.parts = []      # (world verts (n,3), uv (n,2), faces (m,3), material, part of an entrance)
        self.modifiers = modifiers or {}  # path -> TerrainModifier fields (from the raw dump)
        self.entrances = set(entrances)   # paths of the exterior dungeon entrances (Teleport)
        self.terrain = []    # (world position, fields) of each active TerrainModifier
        self.entrance = []   # world positions of the active entrances

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
        m = {"name": "", "tex": None, "tint": np.ones(3), "st": (1, 1, 0, 0), "cutoff": None, "glass": False,
             "skip": False}
        try:
            mat = pptr.read()
            m["name"] = mat.m_Name
            props = mat.m_SavedProperties
            floats, colors = dict(props.m_Floats), dict(props.m_Colors)
            if "_Color" in colors:
                c = colors["_Color"]
                m["tint"] = np.array([c.r, c.g, c.b])
            textured = any(k == "_MainTex" and t.m_Texture.m_PathID for k, t in props.m_TexEnvs)
            m["glass"] = "_RefractionIntensity" in floats and not textured  # force field, not a textured rock
            m["skip"] = bool(SKIP_SHADER_PROPS & floats.keys())
            # The shaders aren't in the server data, so their keywords all land in m_InvalidKeywords.
            keywords = set(getattr(mat, "m_ValidKeywords", None) or []) | set(getattr(mat, "m_InvalidKeywords", None) or [])
            keywords |= set((getattr(mat, "m_ShaderKeywords", None) or "").split())
            gloss_alpha = GLOSS_IN_ALPHA in keywords or floats.get("_SmoothnessTextureChannel") == 1
            for k, t in props.m_TexEnvs:
                if k == "_MainTex" and t.m_Texture.m_PathID:
                    try:
                        m["tex"] = np.asarray(t.m_Texture.read().image.convert("RGBA"), np.float32) / 255
                        m["st"] = (t.m_Scale.x, t.m_Scale.y, t.m_Offset.x, t.m_Offset.y)
                    except Exception:
                        pass
            if (floats.get("_Cutoff", 0) > 0 and not gloss_alpha and m["tex"] is not None
                    and m["tex"][..., 3].min() < 0.5):
                m["cutoff"] = floats["_Cutoff"]
        except Exception:
            pass
        self.mats[key] = m
        return m

    def walk(self, g, chain=None, skip=None, path=None, in_entrance=False):
        """Collect the active renderers under g; the root's own transform is the location origin."""
        skip = set() if skip is None else skip
        if not g.m_IsActive:
            return
        cs = self.components(g)
        tr = cs["Transform"]
        chain = [] if chain is None else chain + [tr]
        path = None if chain == [] else (g.m_Name if not path else f"{path}/{g.m_Name}")
        if path in self.modifiers:
            self.terrain.append((to_world(chain, np.zeros((1, 3)))[0], self.modifiers[path]))
        if path in self.entrances:
            self.entrance.append(to_world(chain, np.zeros((1, 3)))[0])
            in_entrance = True
        if "LODGroup" in cs:
            lods = cs["LODGroup"].m_LODs
            keep = {r.renderer.m_PathID for r in lods[min(LOD, len(lods) - 1)].renderers}
            skip.update(r.renderer.m_PathID for lod in lods for r in lod.renderers if r.renderer.m_PathID not in keep)
        mf, mr = cs.get("MeshFilter"), cs.get("MeshRenderer")
        if mf and mr and mr.m_Enabled and mr._pid not in skip and mf.m_Mesh.m_PathID:
            v, vt, subs = self.mesh(mf.m_Mesh)
            mats = list(mr.m_Materials)
            if len(v) and mats:
                w = to_world(chain, v)
                for i, f in enumerate(subs):
                    m = self.material(mats[min(i, len(mats) - 1)])
                    if len(f) and not m["skip"]:
                        self.parts.append((w, vt, f, m, in_entrance))
        for ch in tr.m_Children:
            self.walk(ch.read().m_GameObject.read(), chain, skip, path, in_entrance)


class Terrain:
    """Heightmap around a location: flat at the origin's height (where the game places it), then each TerrainModifier
    in m_sortOrder as Heightmap.ApplyModifier does: LevelTerrain sets the disc (or square) to the modifier's height +
    m_levelOffset, SmoothTerrain2 lerps toward it with t = 1 - (d / m_smoothRadius) ^ m_smoothPower."""

    def __init__(self, modifiers, x0, x1, z0, z1):
        self.x0, self.z0 = math.floor(x0), math.floor(z0)
        self.xs = np.arange(self.x0, math.ceil(x1) + TERRAIN_STEP, TERRAIN_STEP)
        self.zs = np.arange(self.z0, math.ceil(z1) + TERRAIN_STEP, TERRAIN_STEP)
        X, Z = np.meshgrid(self.xs, self.zs)
        h = np.zeros_like(X)
        for (mx, my, mz), f in sorted(modifiers, key=lambda m: m[1].get("m_sortOrder", 0)):
            target = my + f.get("m_levelOffset", 0)
            d = np.hypot(X - mx, Z - mz)
            if f.get("m_level"):
                r = f.get("m_levelRadius", 0)
                inside = (np.abs(X - mx) <= r) & (np.abs(Z - mz) <= r) if f.get("m_square") else d <= r
                h[inside] = target
            if f.get("m_smooth") and f.get("m_smoothRadius", 0) > 0:
                r = f["m_smoothRadius"]
                inside = d <= r
                t = 1 - (d[inside] / r) ** f.get("m_smoothPower", 3)
                h[inside] += (target - h[inside]) * t
        self.h = h

    def height(self, x, z):
        """Bilinear height; flat (0) outside the grid."""
        fx, fz = (x - self.x0) / TERRAIN_STEP, (z - self.z0) / TERRAIN_STEP
        nx, nz = len(self.xs) - 1, len(self.zs) - 1
        ok = (fx >= 0) & (fz >= 0) & (fx <= nx) & (fz <= nz)
        ix, iz = np.clip(fx.astype(int), 0, nx - 1), np.clip(fz.astype(int), 0, nz - 1)
        tx, tz = np.clip(fx - ix, 0, 1), np.clip(fz - iz, 0, 1)
        h = self.h
        v = (h[iz, ix] * (1 - tx) * (1 - tz) + h[iz, ix + 1] * tx * (1 - tz)
             + h[iz + 1, ix] * (1 - tx) * tz + h[iz + 1, ix + 1] * tx * tz)
        return np.where(ok, v, 0.0)

    def mesh(self):
        """World vertices (n,3) and triangles (m,3) of the grid."""
        X, Z = np.meshgrid(self.xs, self.zs)
        v = np.stack([X.ravel(), self.h.ravel(), Z.ravel()], 1)
        nx = len(self.xs)
        i = (np.arange(len(self.zs) - 1)[:, None] * nx + np.arange(nx - 1)[None, :]).ravel()
        f = np.concatenate([np.stack([i, i + nx, i + 1], 1), np.stack([i + 1, i + nx, i + nx + 1], 1)])
        return v, f


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


def project(w, yaw):
    """World (n,3) -> screen x, screen y (down), depth (away from the camera), for the isometric camera at yaw."""
    cy, sy, cp, sp = math.cos(yaw), math.sin(yaw), math.cos(PITCH), math.sin(PITCH)
    X = w[:, 0] * cy - w[:, 2] * sy
    Z = w[:, 0] * sy + w[:, 2] * cy
    return np.stack([X, -(w[:, 1] * cp + Z * sp), -w[:, 1] * sp + Z * cp], 1)


def facing_yaw(scene, radius):
    """Camera yaw for a location with a dungeon entrance (a Teleport outside the interior): of 8 directions, the one
    that shows most of the entrance's own meshes (the dark doorway) in a small test render; for big locations, the
    direction from the origin to the entrance. Others keep the default."""
    if not scene.entrance:
        return YAW
    if sum(len(p[2]) for p in scene.parts) > PROBE_MAX_TRIS or not any(p[4] for p in scene.parts):
        x, _, z = scene.entrance[0]
        return math.atan2(-x, -z) + ENTRANCE_ANGLE if math.hypot(x, z) > 1.5 else YAW
    yaws = [YAW + k * math.pi / 4 for k in range(8)]
    seen = [render(scene, radius, y, probe=True) for y in yaws]
    return yaws[int(np.argmax(seen))]


def render(scene, radius, yaw=YAW, ground=True, probe=False):
    """Isometric z-buffer render of what is above ground; parts centred further than radius from the origin (or 300 m
    up/down) are left out. With ground, the terrain is drawn too, fading out just past the location. probe: return
    how many pixels of the entrance meshes are visible, from a small render."""
    kept = [p for p in scene.parts if abs(p[0].mean(0)[1]) <= 300 and math.hypot(*p[0].mean(0)[[0, 2]]) <= radius]
    if not kept:
        return 0 if probe else None
    allw = np.concatenate([p[0][np.unique(p[2])] for p in kept])
    margin = min(40.0, max(4.0, 1.8 * max(0.0, -allw[:, 1].min())))  # rays from buried geometry cross this much ground
    lo3, hi3 = allw.min(0), allw.max(0)
    half = max(np.abs(lo3[[0, 2]]).max(), np.abs(hi3[[0, 2]]).max()) + margin  # square around the origin
    terrain = Terrain(scene.terrain, -half, half, -half, half)
    parts = []
    for w, vt, f, m, entrance in kept:
        above = w[:, 1] >= terrain.height(w[:, 0], w[:, 2]) - GROUND_SLACK
        parts.append((project(w, yaw), w, vt, f, m, above, entrance))
    # The drawn ground fades out between the location's footprint and the edge of the terrain grid.
    fade_out = half - 1
    fade_in = min(np.hypot(allw[:, 0], allw[:, 2]).max(), fade_out - 4)
    pts = [p[0][np.unique(p[3])][p[5][np.unique(p[3])]] for p in parts]
    pts = np.concatenate(pts) if pts else np.zeros((0, 3))
    if not len(pts):
        return None
    lo, hi = pts[:, :2].min(0), pts[:, :2].max(0)
    R = PROBE_SIZE if probe else SIZE * SS
    sc = R * (FRAME_FILL_GROUND * 0.95 if ground else FRAME_FILL) / max(hi - lo)  # room for the ground's fade
    off = (R - (hi - lo) * sc) / 2
    # The terrain hides what is behind it: its depth per pixel, drawn only into gd.
    gd = np.full((R, R), np.inf, np.float32)
    gimg = np.zeros((R, R, 4), np.float32)
    gv, gf = terrain.mesh()
    gp = project(gv, yaw)
    gs = (gp[:, :2] - lo) * sc + off
    for fi, px, py, l in triangles(gs, gf, R):
        tri = gf[fi]
        d = l @ gp[tri, 2]
        vis = d < gd[py, px]
        if not vis.any():
            continue
        px, py, d, l = px[vis], py[vis], d[vis], l[vis]
        gd[py, px] = d
        if ground and not probe:
            n = np.cross(gv[tri[1]] - gv[tri[0]], gv[tri[2]] - gv[tri[0]])
            shade = 0.55 + 0.5 * abs(float(n @ LIGHT)) / (np.linalg.norm(n) or 1)
            wp = l @ gv[tri]
            r = np.hypot(wp[:, 0], wp[:, 2])
            gimg[py, px, :3] = GROUND * shade
            gimg[py, px, 3] = np.clip((fade_out - r) / max(fade_out - fade_in, 1), 0, 1) * 0.9
    gd += GROUND_SLACK / math.sin(PITCH)
    zb = np.full((R, R), np.inf, np.float32)
    img = np.zeros((R, R, 4), np.float32)
    for glass_pass in (False, True):  # glass after everything opaque, blended, no depth write
        for p, w, vt, f, m, above, entrance in parts:
            if m["glass"] != glass_pass:
                continue
            s = (p[:, :2] - lo) * sc + off
            for fi, px, py, l in triangles(s, f, R):
                tri = f[fi]
                d = l @ p[tri, 2]
                vis = (d < zb[py, px]) & (d <= gd[py, px])
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
                img[py, px, 3] = 2 if entrance else 1
    if probe:
        return int((img[..., 3] == 2).sum())
    img[..., 3] = np.minimum(img[..., 3], 1)
    ys, xs = np.nonzero(img[..., 3] > 0.02)
    if not len(xs):
        return None
    # Frame what is visible (the terrain hides some of what the bounds counted): a square around it, with a margin
    # for the ground, which fades out toward the frame's edge.
    fill = FRAME_FILL_GROUND if ground else FRAME_FILL
    cx, cy_, half = (xs.min() + xs.max()) / 2, (ys.min() + ys.max()) / 2, max(np.ptp(xs), np.ptp(ys)) / 2 / fill
    box = tuple(int(round(v)) for v in (cx - half, cy_ - half, cx + half, cy_ + half))
    if ground:  # geometry over the terrain
        gy_, gx_ = np.mgrid[0:R, 0:R]
        # round vignette inside the frame (and the canvas, which the frame can overhang)
        reach = min(half, cx, R - cx, cy_, R - cy_)
        rn = np.hypot(gx_ - cx, gy_ - cy_) / max(reach, 1)
        ga = gimg[..., 3:] * np.clip((1 - rn) / 0.3, 0, 1)[..., None]
        a = img[..., 3:]
        alpha = a + ga * (1 - a)
        img[..., :3] = (img[..., :3] * a + gimg[..., :3] * ga * (1 - a)) / np.maximum(alpha, 1e-6)
        img[..., 3:] = alpha
    out = Image.fromarray((img * 255).astype(np.uint8), "RGBA").crop(box)
    return out.resize((SIZE, SIZE), Image.LANCZOS)


def render_location(job):
    name, bundles, extra, raw, out = job
    t = time.time()
    try:
        env = UnityPy.load(*bundles, *extra)
        ab = next(a for a in (o.read() for o in env.objects if o.type.name == "AssetBundle")
                  if any(Path(k).stem == name for k, _ in a.m_Container))
        root = next(v.asset for k, v in ab.m_Container if Path(k).stem == name).read()
        loc = json.loads((raw / "locations" / f"{name}.json").read_text())
        comps = [c for c in loc["components"] if c.get("path")]
        scene = Scene({c["path"]: c["fields"] for c in comps if c["type"] == "TerrainModifier"},
                      {c["path"] for c in comps if c["type"] == "Teleport" and not c["path"].startswith("Interior/")})
        scene.walk(root)
        ext_r = next((c["fields"].get("m_exteriorRadius", 20) for c in loc["components"] if c["type"] == "Location"), 20)
        radius = max(3 * ext_r + 20, 40)
        img = render(scene, radius, facing_yaw(scene, radius))
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
