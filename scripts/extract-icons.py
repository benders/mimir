#!/usr/bin/env python3
"""Extract the icons the dump references, as PNGs, straight from the server's asset bundles.

The headless server can't read its own icon atlas (BC7, no GPU), so the plugin only records
sprite names ({"$sprite": "<name>"}). UnityPy decodes the atlas offline and crops each sprite.

    scripts/extract-icons.py <server_dir> <raw_dump_dir> <out_dir>

Writes <out_dir>/<sprite>.png for every sprite name referenced anywhere in the dump. Fails if a
referenced sprite is missing or ambiguous (two different sprites with that name). Needs UnityPy
(see requirements.txt; scripts/icons.sh sets up the venv).
"""
import os
import re
import sys
from pathlib import Path

import UnityPy

SPRITE_REF = re.compile(r'"\$sprite": "((?:[^"\\]|\\.)*)"')
SKIP_SUFFIXES = (".manifest", ".resS", ".resource", ".json", ".info", ".config", ".dll", ".so", ".txt", ".sh")


def referenced_sprites(raw: Path) -> set[str]:
    names: set[str] = set()
    for f in raw.rglob("*.json"):
        names.update(SPRITE_REF.findall(f.read_text(encoding="utf-8")))
    return names


def asset_files(data_dir: Path):
    for dirpath, dirnames, files in os.walk(data_dir):
        dirnames[:] = [d for d in dirnames if d not in ("Managed", "MonoBleedingEdge", "Plugins")]
        for f in sorted(files):
            if not f.endswith(SKIP_SUFFIXES):
                yield Path(dirpath) / f


def safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", name)


def main() -> int:
    server, raw, out = (Path(a) for a in sys.argv[1:4])
    wanted = referenced_sprites(raw)
    print(f"{len(wanted)} sprites referenced by the dump")

    found: dict[str, list] = {}
    for path in asset_files(server / "valheim_server_Data"):
        try:
            env = UnityPy.load(str(path))
        except Exception:
            continue  # not a Unity asset file
        for obj in env.objects:
            if obj.type.name != "Sprite":
                continue
            sprite = obj.read()
            if sprite.m_Name in wanted:
                found.setdefault(sprite.m_Name, []).append((path, sprite))

    missing = sorted(wanted - found.keys())
    if missing:
        print(f"ERROR: {len(missing)} referenced sprites not found: {missing[:20]}", file=sys.stderr)
        return 1

    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.png"):
        old.unlink()
    files: dict[str, str] = {}
    for name, hits in sorted(found.items()):
        images = [s.image for _, s in hits]
        if any(img.tobytes() != images[0].tobytes() for img in images[1:]):
            print(f"ERROR: sprite name {name!r} is ambiguous: {[str(p) for p, _ in hits]}", file=sys.stderr)
            return 1
        file = safe_name(name) + ".png"
        if file in files.values():
            print(f"ERROR: file name collision for sprite {name!r}", file=sys.stderr)
            return 1
        images[0].save(out / file, optimize=True)
        files[name] = file

    print(f"wrote {len(files)} icons -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
