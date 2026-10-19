#!/usr/bin/env python3
"""Track the game code the mechanics pages cite (#60). Stdlib only.

    scripts/mechanics_sources.py check [--decompiled DIR]            # after a game update (CI)
    scripts/mechanics_sources.py accept PAGE... | --all [--decompiled DIR]   # after re-checking a page by hand

Each page in site/mechanics/*.md names the decompiled methods it was derived from (`sources:` front matter,
`Type.Method`, `Outer.Nested.Method` or a bare type). The committed record site/mechanics/verified.json holds, per
page, the game version it was verified against (`version`) and a hash of each cited method's source:

    {"healing": {"version": "1.0.20", "methods": {"BaseAI.UpdateRegeneration": "<sha256[:16]>", ...},
                 "changed": ["..."], "changedIn": "1.0.21"}}     # last two only while the page is stale

`check` hashes the cited methods in the current decompile (.cache/decompiled, `make decompile`). A page whose
methods all still match moves to the decompiled game version; one with a changed, missing or unrecorded method
keeps its version and gets `changed` / `changedIn`. It prints a Markdown report of the stale pages (nothing when
none are) and exits 0: a stale page is work to do, not a failure. `accept` records the current hashes and version
for pages a human has re-checked (and for a new page or citation). The site shows the page's own version and a
notice while it is stale; tests/test_site.py checks every citation has a recorded hash.

Methods are found by the shape of ILSpy's output (`-p`, one top-level type per file): a declaration line, then
`{` alone on a line and the matching line at its indentation that starts with `}`. All overloads of a name are hashed together;
whitespace is normalized so re-indentation doesn't count as a change.
"""
import argparse
import hashlib
import importlib.util
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGES = ROOT / "site/mechanics"
RECORD = PAGES / "verified.json"
DECOMPILED = ROOT / ".cache/decompiled"

TYPE_RE = re.compile(r"\b(?:class|struct|enum|interface|record)\s+(\w+)")
NAME_RE = re.compile(r"(\w+)(?:<[^()]*>)?\(")


def front_matter_sources(text: str) -> list[str]:
    spec = importlib.util.spec_from_file_location("mechanics", ROOT / "scripts/mechanics.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    meta, _ = m.parse_front_matter(text)
    return [x.strip() for x in meta.get("sources", "").split(";") if x.strip()]


def page_sources(pages: Path = PAGES) -> dict[str, list[str]]:
    return {f.stem: front_matter_sources(f.read_text(encoding="utf-8")) for f in sorted(pages.glob("*.md"))}


def index_source(text: str, blocks: dict[str, list[str]]) -> None:
    """Add the types and methods of one decompiled file to `blocks` (qualified name -> source texts)."""
    lines = text.splitlines()
    stack = []  # [kind, qualified name, indent, first line]

    def indent(s):
        return len(s) - len(s.lstrip("\t"))

    def container():
        return next((f for f in reversed(stack) if f[0] != "namespace"), None)

    for i, line in enumerate(lines):
        s = line.strip()
        if s == "{":
            j = i - 1
            while j >= 0 and not lines[j].strip():
                j -= 1
            header = lines[j].strip() if j >= 0 else ""
            outer = container()
            if header.startswith("namespace "):
                kind, name = "namespace", ""
            elif (outer is None or outer[0] == "type") and (t := TYPE_RE.search(header)) and "(" not in header.split(t.group(0))[0]:
                kind, name = "type", (f"{outer[1]}." if outer else "") + t.group(1)
            elif outer is not None and outer[0] == "type" and (n := NAME_RE.search(header)):
                kind, name = "method", f"{outer[1]}.{n.group(1)}"
            else:
                kind, name = "other", ""  # properties, accessors, statements, initializers
            stack.append([kind, name, indent(line), j])
        elif s.startswith("}") and stack and indent(line) == stack[-1][2]:  # }, };, }); ...
            kind, name, _, start = stack.pop()
            if kind in ("type", "method"):
                blocks[name].append("\n".join(lines[start:i + 1]))
        elif (outer := container()) and outer[0] == "type" and stack[-1][0] in ("type", "namespace") \
                and "=>" in s and s.endswith(";") and (n := NAME_RE.search(s.split("=>")[0])):
            blocks[f"{outer[1]}.{n.group(1)}"].append(s)  # expression-bodied method


def index_dir(root: Path) -> dict[str, list[str]]:
    blocks: dict[str, list[str]] = defaultdict(list)
    for f in sorted(root.rglob("*.cs")):
        index_source(f.read_text(encoding="utf-8", errors="replace"), blocks)
    return blocks


def resolve(cite: str, blocks: dict[str, list[str]]) -> list[str] | None:
    """Source texts of a citation: an exact qualified name, else the one name ending in it (ItemData.X ->
    ItemDrop.ItemData.X). None when nothing or more than one type matches."""
    if cite in blocks:
        return blocks[cite]
    hits = [k for k in blocks if k.endswith("." + cite)]
    return blocks[hits[0]] if len(hits) == 1 else None


def digest(texts: list[str]) -> str:
    norm = sorted(" ".join(t.split()) for t in texts)
    return hashlib.sha256("\n".join(norm).encode()).hexdigest()[:16]


def game_version(root: Path) -> str:
    """Version.CurrentVersion from the decompiled code, so the record names the code it hashed."""
    f = next(root.rglob("Version.cs"), None)
    m = f and re.search(r"CurrentVersion\s*\{[^}]*\}\s*=\s*new GameVersion\(([\d,\s]+)\)", f.read_text(encoding="utf-8"))
    if not m:
        raise SystemExit(f"no Version.CurrentVersion under {root}: run make decompile")
    return ".".join(x.strip() for x in m.group(1).split(","))


def current(sources: dict[str, list[str]], blocks) -> dict[str, dict[str, str | None]]:
    return {page: {c: (digest(t) if (t := resolve(c, blocks)) else None) for c in cites}
            for page, cites in sources.items()}


def check(record: dict, now: dict, version: str) -> dict:
    """The record after a game update: unchanged pages move to `version`, the rest are marked stale."""
    out = {}
    for page, hashes in now.items():
        old = record.get(page, {})
        changed = [c for c, h in hashes.items() if h is None or old.get("methods", {}).get(c) != h]
        entry = {"version": old.get("version", ""), "methods": old.get("methods", {})}
        if not changed and old:
            entry = {"version": version, "methods": hashes}
        else:
            entry |= {"changed": changed, "changedIn": old.get("changedIn", version)}
        out[page] = entry
    return out


def accept(record: dict, now: dict, version: str, pages) -> dict:
    out = dict(record)
    for page in pages:
        missing = [c for c, h in now[page].items() if h is None]
        if missing:
            raise SystemExit(f"{page}: not found in the decompiled code: {', '.join(missing)}")
        out[page] = {"version": version, "methods": now[page]}
    return {p: out[p] for p in now}  # drops deleted pages


def report(record: dict) -> str:
    stale = {p: e for p, e in record.items() if e.get("changed")}
    if not stale:
        return ""
    rows = "\n".join(f"- [ ] **{p}** (verified {e['version'] or 'never'}): " + ", ".join(f"`{c}`" for c in e["changed"])
                     for p, e in stale.items())
    return (f"The game code cited by {len(stale)} mechanics page(s) changed or isn't recorded. Re-check each page "
            f"against `.cache/decompiled/` (`make decompile`), fix it if needed, then record it with "
            f"`make mechanics-accept PAGES=\"...\"`.\n\n{rows}\n")


def save(record: dict) -> None:
    RECORD.write_text(json.dumps(record, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("command", choices=["check", "accept"])
    ap.add_argument("pages", nargs="*")
    ap.add_argument("--all", action="store_true", help="accept every page")
    ap.add_argument("--decompiled", type=Path, default=DECOMPILED)
    a = ap.parse_args()
    if not a.decompiled.is_dir():
        raise SystemExit(f"no decompiled code at {a.decompiled}: run make decompile")
    record = json.loads(RECORD.read_text(encoding="utf-8")) if RECORD.is_file() else {}
    sources = page_sources()
    now = current(sources, index_dir(a.decompiled))
    version = game_version(a.decompiled)
    if a.command == "check":
        record = check(record, now, version)
        print(report(record), end="")
    else:
        pages = list(sources) if a.all else a.pages
        if not pages or (bad := [p for p in pages if p not in sources]):
            raise SystemExit(f"accept: name pages from site/mechanics/ or --all{f' (unknown: {bad})' if pages else ''}")
        record = accept(record, now, version, pages)
        print(f"recorded {len(pages)} page(s) as verified against Valheim {version}", file=sys.stderr)
    save(record)
    return 0


if __name__ == "__main__":
    sys.exit(main())
