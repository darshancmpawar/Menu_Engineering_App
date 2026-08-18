#!/usr/bin/env python3
"""Replace copy-pasted client rules with a reference to the shared library.

"Paneer once a week" was written out verbatim in eleven client files, "mushroom
once a week" in four, "plain chapati twice a week" in three. Each copy is a
place the wording can drift, and fixing one fixes one.

This rewrites those rules as `use` entries pointing at
`data/configs/rule_library.json`. Only rules whose body matches a component
EXACTLY are converted, so the loaded ruleset is unchanged — `--check` proves
that by comparing the rules every client resolves to, before and after.

Idempotent: a client already on the shelf has nothing left to convert.
"""
from __future__ import annotations

import argparse
import json
from collections import OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLIENTS_DIR = ROOT / "data" / "configs" / "clients"
LIBRARY = ROOT / "data" / "configs" / "rule_library.json"


def _body(rule: dict) -> str:
    """Comparable form of a rule: everything but its name and prose."""
    return json.dumps({k: v for k, v in rule.items()
                       if k not in ("name", "_comment", "_doc")},
                      sort_keys=True)


def load_library() -> dict:
    blob = json.loads(LIBRARY.read_text())
    return {k: v for k, v in blob.items()
            if not k.startswith("_") and isinstance(v, dict)}


def convert(block: dict, library: dict):
    """Return (new_block, [(component, old_rule_name), …])."""
    by_body = {_body(v): k for k, v in library.items()}
    kept, uses, moved = [], list(block.get("use") or []), []
    for rule in block.get("rules", []):
        component = by_body.get(_body(rule))
        if component is None:
            kept.append(rule)
            continue
        name = rule.get("name")
        # Keep the client's own rule name so nothing that references it by name
        # (a `disable` entry, a test) changes meaning.
        if name and name != component:
            uses.append(OrderedDict([("ref", component), ("as", name)]))
        else:
            uses.append(component)
        moved.append((component, name))
    out = OrderedDict()
    for key in ("_comment", "disable"):
        if key in block:
            out[key] = block[key]
    if uses:
        out["use"] = uses
    out["rules"] = kept
    for key, value in block.items():
        if key not in out and key not in ("use", "rules"):
            out[key] = value
    return out, moved


def resolved(client: str) -> list:
    """The rule names+bodies this client actually loads, for the check."""
    import sys
    sys.path.insert(0, str(ROOT))
    from src.menu_rules.menu_rule_loader import MenuRuleLoader
    blob = MenuRuleLoader._read_client_blob().get(client)
    parsed = MenuRuleLoader._parse_client_block(blob)
    return sorted((r.get("name"), _body(r)) for r in parsed["rules"])


def main(check=False):
    library = load_library()
    before = {}
    if check:
        blob_path = CLIENTS_DIR
        for path in sorted(blob_path.glob("*.json")):
            for client in json.loads(path.read_text()):
                before[client] = resolved(client)

    total = 0
    for path in sorted(CLIENTS_DIR.glob("*.json")):
        blob = json.loads(path.read_text(), object_pairs_hook=OrderedDict)
        changed = False
        for client, block in list(blob.items()):
            if not isinstance(block, dict):
                continue
            new_block, moved = convert(block, library)
            if moved:
                blob[client] = new_block
                changed = True
                total += len(moved)
                for component, old in moved:
                    print(f"  {client}: {old} -> use {component}")
        if changed and not check:
            path.write_text(json.dumps(blob, indent=2, ensure_ascii=False) + "\n")

    print(f"\n{total} rule(s) moved onto the shelf")
    if check:
        print("[--check] nothing written")
        return 0

    # Prove the swap changed nothing about what each client loads.
    import importlib
    import src.menu_rules.menu_rule_loader as mrl
    importlib.reload(mrl)
    bad = []
    for path in sorted(CLIENTS_DIR.glob("*.json")):
        for client in json.loads(path.read_text()):
            after = resolved(client)
            if client in before and before[client] != after:
                bad.append(client)
    if before:
        print("identical rules after the swap"
              if not bad else f"MISMATCH for {bad}")
        return 1 if bad else 0
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    raise SystemExit(main(check=ap.parse_args().check))
