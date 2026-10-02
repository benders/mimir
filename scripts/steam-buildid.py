#!/usr/bin/env python3
"""Read steamcmd `app_info_print <app>` output on stdin, print the public branch's build id.

    steamcmd ... +app_info_print 896660 +quit | scripts/steam-buildid.py 896660
"""
import re
import sys

TOKEN = re.compile(r'"((?:[^"\\]|\\.)*)"|([{}])')


def parse_vdf(tokens):
    """Text VDF: "key" "value" | "key" { ... }. Returns a dict."""
    out = {}
    for tok, brace in tokens:
        if brace == "}":
            return out
        if brace == "{":
            raise ValueError("unexpected {")
        val, vbrace = next(tokens)
        out[tok] = parse_vdf(tokens) if vbrace == "{" else val
    return out


def main():
    app = sys.argv[1]
    text = sys.stdin.read()
    # steamcmd prints log lines first; the app info block starts at '"<app>"' followed by '{'.
    m = re.search(r'^"%s"\s*\{' % re.escape(app), text, re.M)
    if not m:
        sys.exit(f"steam-buildid: no app_info for {app} in steamcmd output:\n{text[-2000:]}")
    tokens = ((s, b) for s, b in (t.groups() for t in TOKEN.finditer(text, m.start())))
    next(tokens), next(tokens)  # "<app>" {
    info = parse_vdf(tokens)
    branches = info.get("depots", {}).get("branches", {})
    build = branches.get("public", {}).get("buildid", "")
    if not build.isdigit():
        sys.exit(f"steam-buildid: no public build id in app_info: {sorted(branches)}")
    print(build)


if __name__ == "__main__":
    main()
