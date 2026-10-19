#!/usr/bin/env python3
"""Snapshot the live UE MCP toolset/tool inventory.

Cross-platform (macOS/Linux/Windows). Requires UE running with the MCP server
(see SKILL.md -> One-Click Connect).

Usage:
    python3 snapshot_toolsets.py                      # write references/ue<ver>_baseline.json
    python3 snapshot_toolsets.py --out my.json
    python3 snapshot_toolsets.py --diff references/ue583_baseline.json
    python3 snapshot_toolsets.py --url http://127.0.0.1:8000/mcp

What it fixes over naive counting (see references/ue583_baseline.json):
  * list_toolsets prints multi-line descriptions whose bullet lines also start
    with "- ", so a line count over-reports. A real entry is the token before
    ':' matching ^[A-Za-z_][A-Za-z0-9_.]*$ (bullets contain spaces).
  * describe_toolset repeats the toolset's own name once, so counting '"name"'
    over-reports each toolset by exactly 1. We count qualified names
    '"name":"<toolset>.<tool>"' instead.
"""
import argparse
import json
import os
import re
import sys
import urllib.request

DEFAULT_URL = "http://127.0.0.1:8000/mcp"
NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")


class Client:
    def __init__(self, url):
        from ue_mcp.transport import Client as Transport
        self.transport = Transport(url, timeout=180)

    def connect(self):
        self.transport.connect()

    def call(self, tool, args=None, toolset=None):
        result = self.transport.call(tool, args, toolset)
        return "\n".join(item.get("text", "") for item in result.get("content", []))

    def close(self):
        self.transport.close()


def parse_toolsets(raw):
    """Return (real_toolsets, phantom_entries)."""
    toolsets, others = [], []
    for line in raw.split("\n"):
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue
        name = stripped[2:].split(":", 1)[0].strip()
        if not NAME_RE.match(name):
            continue          # description bullet line, not an entry
        if "." in name:
            toolsets.append(name)
        else:
            others.append(name)
    return sorted(set(toolsets)), sorted(set(others))


def snapshot(url):
    c = Client(url)
    c.connect()
    try:
        toolsets, others = parse_toolsets(c.call("list_toolsets"))
        inventory = {}
        for ts in toolsets:
            blob = c.call("describe_toolset", {"toolset_name": ts})
            inventory[ts] = sorted(set(
                re.findall(re.escape('"name":"' + ts + ".") + r'([A-Za-z0-9_]+)"', blob)))
        unique = set()
        for names in inventory.values():
            unique.update(names)
        return {
            "verified": __import__("datetime").date.today().isoformat(),
            "toolset_count": len(inventory),
            "tool_count": sum(len(v) for v in inventory.values()),
            "unique_tool_name_count": len(unique),
            "phantom_list_toolsets_entries": others,
            "toolsets": inventory,
        }
    finally:
        c.close()


def diff(old, new):
    ot, nt = old.get("toolsets", {}), new.get("toolsets", {})
    lines = []
    for ts in sorted(set(ot) | set(nt)):
        if ts not in ot:
            lines.append("+ TOOLSET  {}".format(ts))
        elif ts not in nt:
            lines.append("- TOOLSET  {}".format(ts))
        else:
            added = sorted(set(nt[ts]) - set(ot[ts]))
            removed = sorted(set(ot[ts]) - set(nt[ts]))
            for t in added:
                lines.append("  + {:28s} {}".format(t, ts))
            for t in removed:
                lines.append("  - {:28s} {}".format(t, ts))
    if not lines:
        lines.append("no differences")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Snapshot the live UE MCP tool inventory")
    ap.add_argument("--url")
    ap.add_argument("--instance")
    ap.add_argument("--state-dir")
    ap.add_argument("--out", help="output path (default references/ue<toolsets>_baseline.json)")
    ap.add_argument("--diff", help="compare against this baseline JSON and print the delta")
    args = ap.parse_args()

    from ue_mcp.instances import Store
    store = Store(args.state_dir)
    try:
        url = store.resolve(args.instance, args.url)["url"]
    finally:
        store.close()
    snap = snapshot(url)

    if args.diff:
        with open(args.diff, encoding="utf-8") as f:
            old = json.load(f)
        print("=== drift vs {} ===".format(os.path.basename(args.diff)))
        print("old: {} toolsets / {} tools".format(old.get("toolset_count"), old.get("tool_count")))
        print("new: {} toolsets / {} tools".format(snap["toolset_count"], snap["tool_count"]))
        print()
        print(diff(old, snap))
        return 0

    out = args.out
    if not out:
        here = os.path.dirname(os.path.abspath(__file__))
        out = os.path.join(here, os.pardir, "references", "ue_baseline.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(snap, f, indent=1)
    print("toolsets: {}  tools: {}  unique: {}".format(
        snap["toolset_count"], snap["tool_count"], snap["unique_tool_name_count"]))
    if snap["phantom_list_toolsets_entries"]:
        print("phantom list_toolsets entries (not real toolsets): {}".format(
            ", ".join(snap["phantom_list_toolsets_entries"])))
    print("wrote {}".format(os.path.abspath(out)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
