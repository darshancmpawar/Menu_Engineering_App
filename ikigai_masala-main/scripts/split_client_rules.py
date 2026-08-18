#!/usr/bin/env python3
"""Split `client_rules.json` into one file per client.

`data/configs/client_rules.json` had grown to 2,453 lines holding 36 clients, so
every client edit touched the same document: no way to read one client's rules
without scrolling past everyone else's, and two people editing two different
clients conflict on the same file.

After this, each client is `data/configs/clients/<slug>.json` holding a single
top-level key:

    { "Tekion": { "disable": [...], "rules": [...], "constant_items": {...} } }

**The client name stays inside the file, not in the filename.** The lookup is an
exact byte-for-byte match against `clients.name` and a mismatch is silent — every
rule for that client loads as zero and a plausible plan comes back having ignored
all of them (this already happened once, with `ToastTab CHN` configured while the
file said `Toast Tab CHN`). Names like `Booking.com`, `L&T` and `ToastTab CHN`
do not survive a round trip through a filesystem-safe slug, so the slug is
cosmetic and the key is authoritative.

Idempotent: re-running regenerates identical files. Pass `--check` to verify the
split matches the source without writing (used by the test).
"""
from __future__ import annotations

import argparse
import json
import re
from collections import OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "data" / "configs" / "client_rules.json"
TARGET_DIR = ROOT / "data" / "configs" / "clients"


def slug(name: str) -> str:
    """Filesystem-safe, human-recognisable filename. Cosmetic only."""
    s = re.sub(r"[^a-z0-9]+", "_", name.strip().lower())
    return s.strip("_") or "client"


def load_source() -> "OrderedDict[str, object]":
    with open(SOURCE) as f:
        return json.load(f, object_pairs_hook=OrderedDict)


def load_split() -> "OrderedDict[str, object]":
    """Merge every per-client file back into one blob, as the loader will."""
    merged: "OrderedDict[str, object]" = OrderedDict()
    if not TARGET_DIR.is_dir():
        return merged
    for path in sorted(TARGET_DIR.glob("*.json")):
        with open(path) as f:
            blob = json.load(f, object_pairs_hook=OrderedDict)
        if not isinstance(blob, dict):
            raise ValueError(f"{path.name}: expected an object at the top level")
        for name, block in blob.items():
            if name in merged:
                raise ValueError(
                    f"{path.name}: client {name!r} is already defined in "
                    f"another file — the loader would silently pick one")
            merged[name] = block
    return merged


def write_split(source) -> int:
    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    seen: dict = {}
    for name, block in source.items():
        fn = slug(name)
        if fn in seen:
            fn = f"{fn}_{slug(str(len(seen)))}"
        seen[fn] = name
        with open(TARGET_DIR / f"{fn}.json", "w") as f:
            json.dump({name: block}, f, indent=2, ensure_ascii=False)
            f.write("\n")
    # Remove files for clients that no longer exist in the source.
    for path in TARGET_DIR.glob("*.json"):
        if path.stem not in seen:
            print(f"  - removing stale {path.name}")
            path.unlink()
    return len(seen)


def main(check=False):
    source = load_source() if SOURCE.exists() else OrderedDict()
    if check:
        split = load_split()
        missing = set(source) - set(split)
        extra = set(split) - set(source)
        differing = [k for k in set(source) & set(split) if source[k] != split[k]]
        ok = not (missing or extra or differing)
        print(f"source: {len(source)} clients | split: {len(split)} clients")
        if missing:
            print(f"  MISSING from the split: {sorted(missing)}")
        if extra:
            print(f"  EXTRA in the split: {sorted(extra)}")
        if differing:
            print(f"  DIFFERENT content: {sorted(differing)}")
        print("OK — the split matches the source" if ok else "MISMATCH")
        return 0 if ok else 1
    n = write_split(source)
    print(f"wrote {n} per-client files to {TARGET_DIR.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="verify the split matches the source; write nothing")
    raise SystemExit(main(check=ap.parse_args().check))
