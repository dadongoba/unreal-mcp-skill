#!/usr/bin/env python3
"""Cross-platform schema drift guard (macOS/Linux/Windows) - Python twin of
refresh_schemas.ps1. DEFAULT (offline, UE NOT required): cross-checks the two baked
sources against each other:
    references/tool_schemas.md    (core toolset signatures)
    references/capabilities/*.md  (per-domain param tables, section 3)
Reports DRIFT / WARN / INFO. --live additionally pulls describe_toolset from a running
UE MCP server and diffs live params vs tool_schemas.md.

Usage:
    python3 refresh_schemas.py            # offline cross-check
    python3 refresh_schemas.py --live     # + live diff (UE must be running)
"""
import argparse
import glob
import json
import os
import re
import sys

STOPWORDS = {"str", "ref", "bool", "int", "float", "num", "obj", "optional", "empty",
             "all", "none", "true", "false", "eg", "ie", "etc", "and", "or", "the",
             "with", "for", "use", "default", "if"}

TOOLSETS = [
    "editor_toolset.toolsets.blueprint.BlueprintTools",
    "editor_toolset.toolsets.actor.ActorTools",
    "editor_toolset.toolsets.primitive.PrimitiveTools",
    "editor_toolset.toolsets.object.ObjectTools",
    "editor_toolset.toolsets.scene.SceneTools",
    "editor_toolset.toolsets.asset.AssetTools",
    "EditorToolset.EditorAppToolset",
    "EditorToolset.LogsToolset",
    "editor_toolset.toolsets.skeletal_mesh.SkeletalMeshTools",
    "editor_toolset.toolsets.static_mesh.StaticMeshTools",
    "PhysicsToolsets.PhysicsAssetToolset",
    "editor_toolset.toolsets.material.MaterialTools",
]


def skill_dir():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def parse_param_cell(cell):
    if not cell:
        return []
    c = cell.replace("`", "")
    idx = c.find("\u2014")  # em-dash
    if idx >= 0:
        c = c[:idx]
    c = re.sub(r"\([^)]*\)", " ", c)
    names = []
    for seg in c.split(","):
        s = seg.strip()
        s = re.sub(r"[\[\]{}?<>=].*$", "", s).strip()
        if ":" in s:
            s = s.split(":")[0].strip()
        else:
            s = s.split()[0] if s.split() else ""
        if re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", s) and len(s) > 1 and s.lower() not in STOPWORDS:
            names.append(s)
    seen = []
    for n in names:
        if n not in seen:
            seen.append(n)
    return seen


ROW_RE = re.compile(r"^\|\s*`([^`]+)`\s*\|(.+)\|\s*$")


def parse_tool_schemas(path):
    m = {}
    if not os.path.exists(path):
        return m
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            r = ROW_RE.match(line)
            if not r:
                continue
            tool = r.group(1).strip()
            if "/" in tool:
                continue  # merged rows, not diffable
            m[tool] = parse_param_cell(r.group(2).strip())
    return m


def parse_capability_docs(dirpath):
    m = {}
    if not os.path.isdir(dirpath):
        return m
    for fp in sorted(glob.glob(os.path.join(dirpath, "*.md"))):
        with open(fp, "r", encoding="utf-8") as f:
            for line in f:
                r = ROW_RE.match(line)
                if not r:
                    continue
                tool = re.sub(r"^\w+:\s*", "", r.group(1).strip())
                cell = r.group(2).strip()
                if "/" in tool or not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", tool):
                    continue
                if not re.search(r"[,:]", cell) and cell.strip() != "":
                    continue
                if re.match(r"^(YES|NO|UNKNOWN|silent-fail)", cell):
                    continue  # idempotency-guards tables
                p = parse_param_cell(cell)
                if tool in m:
                    for x in p:
                        if x not in m[tool]:
                            m[tool].append(x)
                else:
                    m[tool] = p
    return m


def offline_check(sd):
    print("=== OFFLINE CROSS-CHECK: tool_schemas.md vs capabilities/*.md ===")
    schemas = parse_tool_schemas(os.path.join(sd, "references", "tool_schemas.md"))
    caps = parse_capability_docs(os.path.join(sd, "references", "capabilities"))
    print("parsed: tool_schemas.md = {} tools, capabilities = {} tools".format(len(schemas), len(caps)))

    drift = warn = info = 0
    for t in sorted(set(schemas) | set(caps)):
        in_s, in_c = t in schemas, t in caps
        if in_s and in_c:
            sp, cp = schemas[t], caps[t]
            inter = [x for x in sp if x in cp]
            only_s = [x for x in sp if x not in cp]
            only_c = [x for x in cp if x not in sp]
            if not inter and (sp or cp):
                print("DRIFT  {}: schemas=[{}] caps=[{}]".format(t, ",".join(sp), ",".join(cp)))
                drift += 1
            elif only_s or only_c:
                print("WARN   {}: only-in-schemas=[{}] only-in-caps=[{}]".format(t, ",".join(only_s), ",".join(only_c)))
                warn += 1
        else:
            src = "tool_schemas-only" if in_s else "caps-only"
            print("INFO   {}: single-source ({})".format(t, src))
            info += 1
    print("--- offline summary: {} DRIFT, {} WARN, {} single-source INFO ---".format(drift, warn, info))
    if drift:
        print("ACTION: fix DRIFT rows first (same tool, disjoint params = one side is stale).")
    return schemas


def live_check(schemas, url):
    print("")
    print("=== LIVE PULL: describe_toolset x {} (UE must be running) ===".format(len(TOOLSETS)))
    from snapshot_toolsets import Client
    client = Client(url)
    client.connect()

    live_map = {}
    for ts in TOOLSETS:
        try:
            txt = client.call("describe_toolset", {"toolset_name": ts})
            sigs = re.findall(r'"name"\s*:\s*"([^"]+)"\s*,\s*"inputSchema"\s*:\s*(\{"type":"object".*?\})', txt)
            for name, schema in sigs:
                n = name.split(".")[-1]
                props = re.findall(r'"([A-Za-z0-9_]+)"\s*:\s*\{', schema)
                uniq = []
                for p in props:
                    if p not in uniq:
                        uniq.append(p)
                live_map[n] = uniq
            print("{}: {} tools parsed".format(ts, len(sigs)))
        except Exception as e:
            print("{} FAILED: {}".format(ts, e))

    print("")
    client.close()
    print("=== LIVE vs tool_schemas.md diff ===")
    ld = lw = 0
    for t in sorted(live_map):
        if t in schemas:
            lp, sp = live_map[t], schemas[t]
            inter = [x for x in lp if x in sp]
            if not inter and lp and sp:
                print("LIVE-DRIFT  {}: live=[{}] schemas=[{}]".format(t, ",".join(lp), ",".join(sp)))
                ld += 1
            else:
                only_l = [x for x in lp if x not in sp]
                if only_l:
                    print("LIVE-WARN   {}: live-only params {} (schemas may omit optionals)".format(t, only_l))
                    lw += 1
        else:
            print("LIVE-INFO   {}: not in tool_schemas.md".format(t))
    print("--- live summary: {} DRIFT, {} WARN ---".format(ld, lw))
    print("NOTE: live pull is best-effort regex parsing; treat LIVE-DRIFT as investigate, not gospel.")


def main():
    ap = argparse.ArgumentParser(description="Cross-platform schema drift guard")
    ap.add_argument("--live", action="store_true", help="also pull live UE schemas")
    ap.add_argument("--url", help="MCP server URL")
    ap.add_argument("--instance")
    ap.add_argument("--state-dir")
    args = ap.parse_args()

    sd = skill_dir()
    schemas = offline_check(sd)
    if args.live:
        from ue_mcp.instances import Store
        store = Store(args.state_dir)
        try:
            url = store.resolve(args.instance, args.url)["url"]
        finally:
            store.close()
        live_check(schemas, url)
    else:
        print("")
        print("(offline mode only - add --live with UE running to also diff live server schemas)")


if __name__ == "__main__":
    sys.exit(main())
