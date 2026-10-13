#!/usr/bin/env python3
"""Render every dumped location as a textured isometric image, straight from the server's asset bundles (#52).

Locations are soft-referenced prefabs in StreamingAssets/SoftRef/Bundles; their meshes, materials and textures sit
in other bundles (loaded transitively through each file's externals) or in Unity's built-in resources (the LOD1 roof
boxes are built-in Cubes). Shaders aren't in the server data, so materials are drawn from `_MainTex` x `_Color` with
a fixed light, a z-buffer and alpha cutout; refraction materials (trader force fields) are drawn as faint glass.

    scripts/extract-renders.py <server_dir> <raw_dump_dir> <out_dir> [--unpacked DIR] [--threads N] [location ...]

The bundles are first unpacked to plain files under --unpacked (default .cache/unpacked/<server_dir name>), once per
set of bundles: UnityPy decompresses a whole bundle in memory, while the unpacked files are memory-mapped, so only
what is read stays resident. Only the bundles the locations depend on are loaded (about a third). A full run peaks
around 4-5 GB with 8 threads.

Writes <out_dir>/<location>.webp (transparent background) for each location with static meshes. Locations whose
buildings come from a DungeonGenerator (camps, villages) or that hold only a creature render nothing. Needs UnityPy,
numpy and numba (see requirements.txt; scripts/renders.sh sets up the venv).
"""
import hashlib
import json
import math
import mmap
import os
import resource
import shutil
import struct
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import UnityPy
from numba import njit
from UnityPy.enums.BundleFile import CompressionFlags
from UnityPy.helpers import CompressionHelper
from PIL import Image

SIZE, SS = 800, 2                       # output px, supersampling factor
LOD = 1                                 # LODGroup level: the game's distance view, simpler and closer to how players spot it
YAW, PITCH = math.radians(45), math.radians(30)
LIGHT = np.array([0.35, 0.85, 0.4]) / np.linalg.norm([0.35, 0.85, 0.4])
ENTRANCE_ANGLE = math.radians(30)       # camera this far round from straight at a dungeon entrance
FRAME_FILL, FRAME_FILL_GROUND = 0.92, 0.8  # share of the frame the location fills (without / with drawn ground)
THREADS = 8                             # render threads (each holds ~100 MB of frame buffers)
PROBE_SIZE, PROBE_MAX_TRIS = 200, 60000  # entrance-facing test renders: px, and the largest location worth it
TERRAIN_STEP = 1.0                      # m between heightmap vertices (Heightmap.m_scale)
GROUND_SLACK = 0.1                      # m below the ground still drawn (foundations meet the terrain)
GROUND = np.array([0.52, 0.49, 0.42])    # terrain colour when drawn
GLASS = np.array([0.75, 0.88, 1.0])     # colour of refraction (force field) surfaces
RENDER_COMPONENTS = {"Transform", "RectTransform", "LODGroup", "MeshFilter", "MeshRenderer"}
SKIP_SHADER_PROPS = {"_CentralFade"}    # light beam effect shader (CharredFortress beacon)
GLOSS_IN_ALPHA = "_SMOOTHNESS_TEXTURE_ALBEDO_CHANNEL_A"  # _MainTex alpha is smoothness, not transparency


def _cstr(f):
    out = bytearray()
    while (c := f.read(1)) not in (b"\0", b""):
        out += c
    return out.decode()


def unpack_bundle(path: Path, dest: Path):
    """Stream-decompress one UnityFS bundle (the layout BundleFile.read_fs reads) block by block into dest/<node> files,
    holding one block in memory. .resource nodes (audio, video) are left out: renders never read them."""
    with open(path, "rb") as f:
        assert _cstr(f) == "UnityFS", path
        version, = struct.unpack(">I", f.read(4))
        _cstr(f), _cstr(f)  # player and engine versions
        size, csize, usize, flags = struct.unpack(">qIII", f.read(20))
        if version >= 7:
            f.seek((f.tell() + 15) & ~15)
        if flags & 0x80:  # ArchiveFlags.BlocksInfoAtTheEnd
            pos = f.tell()
            f.seek(size - csize)
            info = f.read(csize)
            f.seek(pos)
        else:
            info = f.read(csize)
        info = CompressionHelper.DECOMPRESSION_MAP[CompressionFlags(flags & 0x3F)](info, usize)
        o = 16  # uncompressed data hash
        count, = struct.unpack_from(">i", info, o)
        blocks = [struct.unpack_from(">IIH", info, o + 4 + 10 * i) for i in range(count)]
        o += 4 + 10 * count
        count, = struct.unpack_from(">i", info, o)
        o += 4
        nodes = []
        for _ in range(count):
            offset, length, _flags = struct.unpack_from(">qqI", info, o)
            end = info.index(b"\0", o + 20)
            nodes.append((offset, length, info[o + 20:end].decode()))
            o = end + 1
        if flags & 0x200:  # ArchiveFlags.BlockInfoNeedPaddingAtStart
            f.seek((f.tell() + 15) & ~15)
        dest.mkdir(parents=True, exist_ok=True)
        data = dest / ".data"
        with open(data, "wb") as w:
            for usize, csize, bflags in blocks:
                block = f.read(csize)
                comp = CompressionFlags(bflags & 0x3F)
                w.write(block if comp == CompressionFlags.NONE else
                        CompressionHelper.DECOMPRESSION_MAP[comp](block, usize))
    with open(data, "rb") as r:
        for offset, length, name in nodes:
            if name.endswith(".resource"):
                continue
            r.seek(offset)
            with open(dest / Path(name).name, "wb") as w:
                while length:
                    chunk = r.read(min(1 << 20, length))
                    w.write(chunk)
                    length -= len(chunk)
    data.unlink()


def open_mapped(env, path: Path):
    """Load an unpacked file into env from a read-only memory map (pages are read on demand, and can be dropped)."""
    with open(path, "rb") as f:
        mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
    return env.load_file(memoryview(mm), name=path.name)


def unpacked_index(bdir: Path, unpacked: Path, locations):
    """Unpack the bundles into unpacked/ (redone when the bundle set changes) and index them, each file alone so only
    one is in memory: CAB name -> bundle, bundle -> referenced CABs, location prefab -> bundle. Cached in index.json."""
    stamp = hashlib.sha1("".join(f"{b.name} {b.stat().st_size}\n" for b in sorted(bdir.iterdir())).encode()).hexdigest()
    idx = unpacked / "index.json"
    if idx.exists():
        cached = json.loads(idx.read_text())
        if cached["stamp"] == stamp:
            return cached["cab2b"], cached["ext"], cached["prefabs"]
    marker = unpacked / ".mimir-unpacked"  # only ever delete a directory this function made
    if unpacked.exists() and any(unpacked.iterdir()) and not marker.exists():
        raise SystemExit(f"{unpacked} exists and wasn't made by extract-renders.py; not replacing it")
    shutil.rmtree(unpacked, ignore_errors=True)
    unpacked.mkdir(parents=True)
    marker.touch()
    for b in sorted(bdir.iterdir()):
        unpack_bundle(b, unpacked / b.name)
    cab2b, ext, prefabs = {}, {}, {}
    for d in sorted(p for p in unpacked.iterdir() if p.is_dir()):
        for node in sorted(d.iterdir()):
            cab2b[node.name] = d.name
            if node.name.endswith(".resS"):
                continue
            sf = open_mapped(UnityPy.Environment(), node)
            ext.setdefault(d.name, []).extend(x.path.split("/")[-1] for x in getattr(sf, "externals", None) or [])
            for o in (getattr(sf, "objects", None) or {}).values():
                if o.type.name == "AssetBundle":
                    for k, _ in o.read().m_Container:
                        if k.endswith(".prefab"):
                            prefabs[Path(k).stem] = d.name
    prefabs = {k: v for k, v in prefabs.items() if k in locations}
    idx.write_text(json.dumps({"stamp": stamp, "cab2b": cab2b, "ext": ext, "prefabs": prefabs}))
    return cab2b, ext, prefabs


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


@njit(cache=True, nogil=True)
def _tri_box(ax, ay, bx, by, cx, cy, R):
    x0 = max(int(math.floor(min(ax, bx, cx))), 0)
    y0 = max(int(math.floor(min(ay, by, cy))), 0)
    x1 = min(int(math.ceil(max(ax, bx, cx))), R - 1)
    y1 = min(int(math.ceil(max(ay, by, cy))), R - 1)
    return x0, y0, x1, y1


@njit(cache=True, nogil=True)
def raster_ground(gs, gz, gv, gf, gd, gimg, draw, fade_in, fade_out, light, col):
    """Terrain triangles: nearest depth into gd; with draw, shaded colour and the radial fade into gimg."""
    R = gd.shape[0]
    for t in range(gf.shape[0]):
        i0, i1, i2 = gf[t, 0], gf[t, 1], gf[t, 2]
        ax, ay, bx, by, cx, cy = gs[i0, 0], gs[i0, 1], gs[i1, 0], gs[i1, 1], gs[i2, 0], gs[i2, 1]
        den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(den) < 1e-9:
            continue
        x0, y0, x1, y1 = _tri_box(ax, ay, bx, by, cx, cy, R)
        shade = 0.0
        if draw:
            ux, uy, uz = gv[i1, 0] - gv[i0, 0], gv[i1, 1] - gv[i0, 1], gv[i1, 2] - gv[i0, 2]
            vx, vy, vz = gv[i2, 0] - gv[i0, 0], gv[i2, 1] - gv[i0, 1], gv[i2, 2] - gv[i0, 2]
            nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
            nl = math.sqrt(nx * nx + ny * ny + nz * nz)
            shade = 0.55 + 0.5 * abs(nx * light[0] + ny * light[1] + nz * light[2]) / (nl if nl > 0 else 1.0)
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                px, py = x + 0.5, y + 0.5
                l0 = ((by - cy) * (px - cx) + (cx - bx) * (py - cy)) / den
                l1 = ((cy - ay) * (px - cx) + (ax - cx) * (py - cy)) / den
                l2 = 1 - l0 - l1
                if l0 < 0 or l1 < 0 or l2 < 0:
                    continue
                d = l0 * gz[i0] + l1 * gz[i1] + l2 * gz[i2]
                if d >= gd[y, x]:
                    continue
                gd[y, x] = d
                if draw:
                    wx = l0 * gv[i0, 0] + l1 * gv[i1, 0] + l2 * gv[i2, 0]
                    wz = l0 * gv[i0, 2] + l1 * gv[i1, 2] + l2 * gv[i2, 2]
                    a = (fade_out - math.sqrt(wx * wx + wz * wz)) / max(fade_out - fade_in, 1.0)
                    for k in range(3):
                        gimg[y, x, k] = col[k] * shade
                    gimg[y, x, 3] = min(max(a, 0.0), 1.0) * 0.9


@njit(cache=True, nogil=True)
def raster_mesh(S, Dz, W, UV, F, tri_mat, tri_ent, glass_pass, tex, tex_off, tex_w, tex_h, st, tint, cutoff,
                is_glass, gd, zb, img, light, view, glass_col):
    """Location triangles in order, z-buffered and behind-the-terrain tested. Opaque pass: textured (nearest texel,
    wrapped, _MainTex_ST), alpha cutout, flat Lambert shade; alpha 2 marks entrance meshes. Glass pass: blended rim
    that grows toward grazing angles, no depth write."""
    R = zb.shape[0]
    for t in range(F.shape[0]):
        m = tri_mat[t]
        if is_glass[m] != glass_pass:
            continue
        i0, i1, i2 = F[t, 0], F[t, 1], F[t, 2]
        ax, ay, bx, by, cx, cy = S[i0, 0], S[i0, 1], S[i1, 0], S[i1, 1], S[i2, 0], S[i2, 1]
        den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(den) < 1e-9:
            continue
        x0, y0, x1, y1 = _tri_box(ax, ay, bx, by, cx, cy, R)
        if x1 < x0 or y1 < y0:
            continue
        ux, uy, uz = W[i1, 0] - W[i0, 0], W[i1, 1] - W[i0, 1], W[i1, 2] - W[i0, 2]
        vx, vy, vz = W[i2, 0] - W[i0, 0], W[i2, 1] - W[i0, 1], W[i2, 2] - W[i0, 2]
        nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
        nl = math.sqrt(nx * nx + ny * ny + nz * nz)
        if nl == 0:
            nl = 1.0
        shade = 0.5 + 0.6 * abs(nx * light[0] + ny * light[1] + nz * light[2]) / nl
        facing = abs(nx * view[0] + ny * view[1] + nz * view[2]) / nl
        rim = 0.06 + 0.5 * (1 - facing) ** 3
        off, tw, th = tex_off[m], tex_w[m], tex_h[m]
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                px, py = x + 0.5, y + 0.5
                l0 = ((by - cy) * (px - cx) + (cx - bx) * (py - cy)) / den
                l1 = ((cy - ay) * (px - cx) + (ax - cx) * (py - cy)) / den
                l2 = 1 - l0 - l1
                if l0 < 0 or l1 < 0 or l2 < 0:
                    continue
                d = l0 * Dz[i0] + l1 * Dz[i1] + l2 * Dz[i2]
                if d >= zb[y, x] or d > gd[y, x]:
                    continue
                if glass_pass:
                    for k in range(3):
                        img[y, x, k] = img[y, x, k] * (1 - rim) + glass_col[k] * rim
                    img[y, x, 3] = max(img[y, x, 3], rim)
                    continue
                r, g, b, a = 0.6, 0.6, 0.6, 1.0
                if off >= 0:
                    u = l0 * UV[i0, 0] + l1 * UV[i1, 0] + l2 * UV[i2, 0]
                    v = l0 * UV[i0, 1] + l1 * UV[i1, 1] + l2 * UV[i2, 1]
                    u = (u * st[m, 0] + st[m, 2]) % 1.0
                    v = (v * st[m, 1] + st[m, 3]) % 1.0
                    tx = min(int(u * tw), tw - 1)
                    ty = min(int((1 - v) * th), th - 1)
                    k = off + (ty * tw + tx) * 4
                    r, g, b, a = tex[k], tex[k + 1], tex[k + 2], tex[k + 3]
                if cutoff[m] >= 0 and a < cutoff[m]:
                    continue
                zb[y, x] = d
                img[y, x, 0] = min(max(r * tint[m, 0] * shade, 0.0), 1.0)
                img[y, x, 1] = min(max(g * tint[m, 1] * shade, 0.0), 1.0)
                img[y, x, 2] = min(max(b * tint[m, 2] * shade, 0.0), 1.0)
                img[y, x, 3] = 2.0 if tri_ent[t] else 1.0


def material_table(scene):
    """Every material of the scene packed for raster_mesh (built once per scene): id by object, flat RGBA texels."""
    if getattr(scene, "_table", None) is None:
        mats, ids = [], {}
        for p in scene.parts:
            if id(p[3]) not in ids:
                ids[id(p[3])] = len(mats)
                mats.append(p[3])
        texs, offs, off = [], [], 0
        for m in mats:
            if m["tex"] is None:
                offs.append(-1)
            else:
                offs.append(off)
                texs.append(m["tex"].ravel())
                off += m["tex"].size
        scene._table = (ids, dict(
            tex=np.concatenate(texs).astype(np.float32) if texs else np.zeros(4, np.float32),
            tex_off=np.array(offs, np.int64),
            tex_w=np.array([0 if m["tex"] is None else m["tex"].shape[1] for m in mats], np.int64),
            tex_h=np.array([0 if m["tex"] is None else m["tex"].shape[0] for m in mats], np.int64),
            st=np.array([m["st"] for m in mats], np.float64).reshape(-1, 4),
            tint=np.array([m["tint"] for m in mats], np.float64).reshape(-1, 3),
            cutoff=np.array([-1.0 if m["cutoff"] is None else m["cutoff"] for m in mats], np.float64),
            is_glass=np.array([m["glass"] for m in mats], np.bool_)))
    return scene._table


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
    # The terrain hides what is behind it: its depth per pixel into gd (and, drawn, its colour into gimg).
    gd = np.full((R, R), np.inf, np.float32)
    gimg = np.zeros((R, R, 4), np.float32)
    gv, gf = terrain.mesh()
    gp = project(gv, yaw)
    raster_ground((gp[:, :2] - lo) * sc + off, gp[:, 2].copy(), gv, gf.astype(np.int64), gd, gimg,
                  ground and not probe, float(fade_in), float(fade_out), LIGHT, GROUND)
    gd += GROUND_SLACK / math.sin(PITCH)
    zb = np.full((R, R), np.inf, np.float32)
    img = np.zeros((R, R, 4), np.float32)
    ids, table = material_table(scene)
    base = np.cumsum([0] + [len(p[1]) for p in parts])
    P = np.concatenate([p[0] for p in parts])
    F = np.concatenate([p[3] + b for p, b in zip(parts, base)]).astype(np.int64)
    tri_mat = np.concatenate([np.full(len(p[3]), ids[id(p[4])], np.int64) for p in parts])
    tri_ent = np.concatenate([np.full(len(p[3]), bool(p[6])) for p in parts])
    W = np.concatenate([p[1] for p in parts])
    UV = np.concatenate([p[2] for p in parts])
    cy, sy, cp, sp = math.cos(yaw), math.sin(yaw), math.cos(PITCH), math.sin(PITCH)
    view = np.array([cp * sy, -sp, cp * cy])  # depth direction
    for glass_pass in (False, True):  # glass after everything opaque, blended, no depth write
        raster_mesh((P[:, :2] - lo) * sc + off, P[:, 2].copy(), W, UV, F, tri_mat, tri_ent, glass_pass, table["tex"],
                    table["tex_off"], table["tex_w"], table["tex_h"], table["st"], table["tint"], table["cutoff"],
                    table["is_glass"], gd, zb, img, LIGHT, view, GLASS)
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


def render_location(name, root, raw, out, lock):
    """Read the location from the shared environment (UnityPy isn't thread-safe: under lock), then render it (numpy
    and the nogil kernels, in parallel with other threads)."""
    t = time.time()
    try:
        loc = json.loads((raw / "locations" / f"{name}.json").read_text())
        comps = [c for c in loc["components"] if c.get("path")]
        scene = Scene({c["path"]: c["fields"] for c in comps if c["type"] == "TerrainModifier"},
                      {c["path"] for c in comps if c["type"] == "Teleport" and not c["path"].startswith("Interior/")})
        with lock:
            scene.walk(root.read())
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


def warm_up():
    """Run each kernel once on a single triangle, so numba compiles (or loads its cache) here."""
    R = 4
    v = np.array([[0.0, 0, 0], [1, 0, 0], [0, 0, 1]])
    f = np.array([[0, 1, 2]], np.int64)
    s2 = np.array([[0.0, 0], [3, 0], [0, 3]])
    gd, zb, img = np.full((R, R), np.inf, np.float32), np.full((R, R), np.inf, np.float32), np.zeros((R, R, 4), np.float32)
    raster_ground(s2, np.zeros(3), v, f, gd, img, True, 1.0, 2.0, LIGHT, GROUND)
    raster_mesh(s2, np.zeros(3), v, np.zeros((3, 2)), f, np.zeros(1, np.int64), np.zeros(1, np.bool_), False,
                np.ones(4, np.float32), np.zeros(1, np.int64), np.ones(1, np.int64), np.ones(1, np.int64),
                np.array([[1.0, 1, 0, 0]]), np.ones((1, 3)), np.array([-1.0]), np.zeros(1, np.bool_),
                gd, zb, img, LIGHT, LIGHT, GLASS)


def main():
    args = sys.argv[1:]
    opts = {}
    for opt in ("--unpacked", "--threads"):
        if opt in args:
            i = args.index(opt)
            opts[opt] = args[i + 1]
            del args[i:i + 2]
    server, raw, out = Path(args[0]), Path(args[1]), Path(args[2])
    unpacked = Path(opts.get("--unpacked", Path(".cache/unpacked") / server.name))
    threads = int(opts.get("--threads", THREADS))
    data = server / "valheim_server_Data"
    bdir = data / "StreamingAssets/SoftRef/Bundles"
    out.mkdir(parents=True, exist_ok=True)
    t = time.time()
    locations = {p.stem for p in (raw / "locations").glob("*.json")}
    cab2b, ext, prefabs = unpacked_index(bdir, unpacked, locations)
    print(f"indexed {len(cab2b)} unpacked files in {time.time() - t:.0f} s", flush=True)
    names = args[3:] or sorted(locations)
    jobs, failed = [], 0
    for n in names:
        if n not in prefabs:
            print(f"{n}: FAILED no bundle")
            failed += 1
            continue
        jobs.append((n, deps(prefabs[n], cab2b, ext)))
    # One environment with just the bundles these locations use (~255 of 798 for all), memory-mapped.
    env = UnityPy.Environment()
    for b in sorted({b for _, ds in jobs for b in ds}):
        for node in sorted((unpacked / b).iterdir()):
            open_mapped(env, node)
    env.load_file(str(data / "Resources/unity default resources"))
    roots = {}
    for b in {prefabs[n] for n, _ in jobs}:
        for f in (unpacked / b).iterdir():
            sf = env.files.get(f.name)
            for o in (getattr(sf, "objects", None) or {}).values():
                if o.type.name == "AssetBundle":
                    for k, v in o.read().m_Container:
                        if k.endswith(".prefab") and Path(k).stem in prefabs:
                            roots[Path(k).stem] = v.asset
    print(f"loaded {len(env.files)} files in {time.time() - t:.0f} s", flush=True)
    # Largest first, so the slowest renders don't start last. Size = the bytes each location's bundles unpack to,
    # each bundle's share split between the locations that use it (shared material/texture bundles count little).
    users = {}
    for _, ds in jobs:
        for b in ds:
            users[b] = users.get(b, 0) + 1
    size = {b: sum(f.stat().st_size for f in (unpacked / b).iterdir()) for b in users}
    jobs.sort(key=lambda j: -sum(size[b] / users[b] for b in j[1]))
    warm_up()  # compile the kernels once (cached on disk)
    lock = threading.Lock()
    with ThreadPoolExecutor(threads) as pool:
        futures = [pool.submit(render_location, n, roots[n], raw, out, lock) for n, _ in jobs]
        for fut in as_completed(futures):
            name, msg, dt = fut.result()
            print(f"{name}: {msg} ({dt:.0f} s)", flush=True)
            failed += msg.startswith("FAILED")
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1e9 if sys.platform == "darwin" else 1e6)
    print(f"{len(list(out.glob('*.webp')))} renders in {time.time() - t:.0f} s, peak RSS {peak:.1f} GB")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
