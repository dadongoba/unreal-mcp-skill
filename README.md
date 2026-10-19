# unreal-mcp-skill

**English** · [简体中文](README.zh-CN.md)

> A **client-neutral Agent Skill and MCP runtime** for Unreal Engine 5.8+: blueprint authoring, scenes, materials, animation, physics and UI from compatible AI clients.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## What it is

A portable knowledge package and Python runtime operating UE via Epic's **ModelContextProtocol** toolsets (available toolsets depend on engine version and enabled plugins). Compatible hosts can use standard MCP tools, native Skills or the command-line helpers:

- **Blueprint DSL workflows** — create BPs, variables, functions, cross-BP calls, compile, PIE-verify; a Scheme-like DSL (`write_graph_dsl`) with 27 battle-tested syntax laws
- **Scene / physics / collision** — component selection rules, trigger patterns, runtime physics activation
- **Materials / UMG / Niagara / Sequencer / PCG / ControlRig / SkeletalMesh** — verified pipelines per domain
- **One-Click Connect** — `ue_connect.py` diagnoses the editor/port/plugins and launches UE for you (novice-friendly)
- **A pitfall lawbook** — 17 law-groups (G1-G17) distilled from real failure forensics: palette-name vs tool-id namespaces, cast-node naming traps, Chinese-locale display-name localization, ghost port squatters...
- **Offline node dictionary + search tools** — 1665-node dictionary + PIE-verified extras, searchable in seconds

Every rule carries a confidence tag: `[VERIFIED <date> UE<ver>-<lang>]` (PIE-proven), `[DOC]` (docs-sourced), or `[UNVERIFIED]`.

## Quick start

1. **Install the shared runtime** from a trusted checkout, then generate the MCP configuration:
   ~~~text
   python scripts/unreal_mcp.py install --source .
   python scripts/unreal_mcp.py config
   python scripts/unreal_mcp.py doctor
   ~~~
   For hosts with native Skills, add the small shared adapter:
   `python scripts/unreal_mcp.py adapter --skill-dir <CLIENT_SKILLS_DIRECTORY>/unreal-mcp`.
   See [universal setup and compatibility](references/universal-runtime.md).
2. **Ensure a UE5.8+ project** whose `.uproject` enables these plugins (the skill can add them with your consent):
   `ModelContextProtocol` · `ToolsetRegistry` · `EditorToolset` · `PythonScriptPlugin` · `AllToolsets`
3. **Register the intended editor** using Python 3.10+ (standard library only):
   ~~~text
   python scripts/ue_connect.py register --instance main --project <PROJECT.uproject> --engine <UE_ROOT> --port 8011
   python scripts/ue_connect.py launch --instance main
   python scripts/ue_connect.py wait --instance main
   ~~~
   Use [independent instances](references/multi-instance.md) for multiple editors.
   Managed writes require a task binding; existing raw write calls must migrate.

## v3.18 shared runtime

- MCP stdio and authenticated loopback HTTP; no particular AI client required.
- Session-owned task lifecycle and published knowledge tools for MCP-only hosts.
- One local core package with small client adapters, diagnostics and version checks.
- Manifest-verified upgrades, active-task guards and previous-version rollback.
- Reviewed experience promotion and portable release automation.

- Independent instance/project ownership, listener identity checks and separate sessions.
- JSON/SSE transport and explicit errors; uncertain writes are never blindly replayed.
- Local experience records, privacy checks and opt-in contributions to this original repository.
- A recoverable [completion wrapper](references/experience-contribution.md) for command-based hosts.
- Runtime data lives in ~/.unreal-mcp, separately from the installed skill.

The contribution workflow must be merged onto master and the owner must enable
Actions PR creation before inbox PRs can be created. Default contribution mode
is local; every user chooses whether to enable public uploading. See
[contribution setup](references/experience-contribution.md).

Validation: simulated HTTP/SSE and local-state regression tests; live dual-UE
operation and end-to-end public intake still require deployment validation.


The bridge can start before UE; register the intended instance and start UE before
beginning an editor task. Reconnect a client after changing its MCP configuration
or activating a new runtime. Discovery behavior depends on the host.

## ⚠️ Known limitation: use the ENGLISH editor interface

This skill is validated against UE 5.8 running with the **English (EN) editor language**.
Do NOT switch the editor to Chinese (or another localized UI) while driving it via MCP:

- Node `type_id`s are matched against palette/registry names. In a localized editor some
  families are renamed (e.g. the Cast category `Utilities|Casting|` displays as
  `工具|Casting|` in a Chinese editor), so node creation by id silently fails.
- Every verified rule in this repo is tagged `[VERIFIED ... UE5.8-EN]` — proven on
  English-locale editors only.

**If your editor is in Chinese**: switch via `Edit → Editor Preferences → Region & Language
→ Editor Language = English`, then restart the editor. Note the console command
`culture = en` is NOT sufficient — it does not affect blueprint node display names
(details in `references/ue_conventions.md` §10).

## Platform support

| | Windows | macOS |
|---|---|---|
| Editor launch | `UnrealEditor.exe` | `.app` inner binary — see `references/platform-macos.md` |
| Helper scripts | PowerShell twins (`.ps1`) | Python twins (`.py`, stdlib only) |
| MCP layer | identical (port 8000, HTTP JSON-RPC) | identical |

## Repository layout

```
SKILL.md                     # router + lawbook (G1-G17) + protocols — start here
references/
  capabilities/*.md          # 11 per-domain capability docs (design rules + tool params)
  dsl_syntax.md              # DSL grammar R1-R27 with verified examples
  node_types.md              # node type_id reference (namespace laws)
  ue_conventions.md          # design-time knowledge (components/collision/UI/zh-locale)
  node_dict_extras.json      # PIE-verified nodes missing from the main dictionary
  node_dictionary_merged.json# 1665-node engine dictionary (searchable, not readable)
  platform-macos.md          # macOS environment twin
  few_shots.md               # behavioral cases (ask/decline/gates)
  history/                   # test achievements + a real-world failure case study
  templates/                 # 17 verified workflow templates (ADAPT, don't copy)
scripts/
  ue_connect.py              # one-click connectivity (check/launch/wait/all)
  mcp_call.py / .ps1         # MCP HTTP callers (file-based args; no quoting hell)
  search_node_dict.py / .ps1 # offline node/pin lookup
  refresh_schemas.py / .ps1  # schema drift guard (offline cross-check + --live)
  bp_template.py, verify_bp.py, import_asset.ps1 ...
```

## Language

Skill content is English-first with Chinese trigger phrases preserved (the skill was built in a mixed zh/en workflow — Chinese users get native phrasing like "连不上/帮我打开项目"). Contributions in either language are welcome.

## Contributing

The skill self-maintains: failures that get diagnosed + verified are promoted into law entries (see *Self-Maintenance Protocol* in SKILL.md). PRs that add `[VERIFIED]` lessons from real PIE runs are the most valuable.

## License

[MIT](LICENSE) — the knowledge base, scripts and templates. Unreal Engine is a trademark of Epic Games, Inc.; this project is not affiliated with or endorsed by Epic Games.
