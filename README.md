# unreal-mcp-skill

**English** · [简体中文](README.zh-CN.md)

> A **client-neutral Agent Skill and MCP runtime** for Unreal Engine, with a three-layer access model: knowledge, live-editor MCP, and native batch CLI. Real-editor validation: UE 5.8.3/5.8.4 and UE 5.9.0; UE 5.7 has adapter protocol coverage only (capability claims stay `[UNV]` until a real 5.7 capture).

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

## Three access layers — route before acting

Pick the layer by the job; they complement, never replace, each other:

| Layer | Entry | Use for |
|---|---|---|
| Knowledge | `ue_knowledge_read` / `launch.py knowledge read` | reading rules and references, no editor needed |
| Live editor | MCP `ue_*` tools attached to a running editor | authoring and verifying graphs, scenes, assets |
| Batch CLI | `UnrealEditor-Cmd.exe` (headless, starts and exits) | bulk compile/validate/cook, scripted jobs over many assets |

The batch layer is UE's own command line — `CompileAllBlueprints`, `DataValidation`, commandlets, `-run=pythonscript` — verified end-to-end on the 5.8.4 test bed. It does **not** occupy an editor instance. See [UE native CLI batch](references/ue-cli-batch.md) before running a job; its task locks and side effects differ from MCP calls.

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

## v3.20 automatic upstream plugin setup

- ue_setup_project detects the selected engine and automatically installs or
  updates a matching stable GitHub plugin, with SHA256/provenance/BuildId checks.
- Upstream Releases are refreshed daily when setup is used. Future matching 5.6
  or earlier assets from the reviewed provider can be discovered; absent assets
  are not advertised as supported. No background watcher is installed.
- Per-project backups/ports, no silent overwrites or editor shutdown, and a
  read-only ue_plugin_status tool. [Setup details](references/plugin-setup.md).

## Backend and update discovery

- Inspect live tool schemas with ue_capabilities; select Epic, Avatar or explicit
  native MCP dispatch. [Compatibility and evidence](references/backends.md).
- ue_status checks the original repository's stable release once per 24 hours,
  shared across clients. ue_check_update supports fresh/offline checks. Failed
  checks remain unknown; historical Releases without portable assets are unpublished.
- Detection does not install anything. Active/running package identity, upgrade
  guards and rollback remain separate. [Update discovery](references/update-discovery.md).

## Versioned capability knowledge (5.7 / 5.8 / 5.9)

Capability verdicts are version-scoped, not inherited. One baseline per engine major —
`ue583_baseline.json` (5.8.3), `ue59_baseline.json` (5.9.0), `ue57_baseline.json` (5.7 placeholder, all `[UNV]`). An `[ABS]` verdict is valid only for the exact build + live toolset set it was captured on; older than one minor it is `[STALE]`.

- **UE 5.9** adds toolsets that overturn several 5.8 "impossible" verdicts (console, file I/O, source control, profiler, MetaSound, gameplay-ability authoring) and renames the whole toolset namespace. Always read the versioned recheck before promising a capability. See [capability boundaries](references/capability_boundaries.md) §6.3–§6.5.
- **Version isolation policy:** isolate at the data/runtime layer (per-major baselines, per-process instances/ports, per-version test projects, backend selected by live schema), but share one skill package and one CLI layer. Do not fork a package per version. See §8 of the same document.
- 5.7 uses a third-party backend, not Epic-native MCP. Its capability file is a placeholder until a real editor capture is done; never inherit 5.8/5.9 `[V]`/`[ABS]` results onto it.

## Shared runtime

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

Validation: simulated HTTP/SSE, local-state regressions, official SDK interop,
a [real Windows UE 5.8.3 dual-editor run](references/validation/ue583-dual-editor-20261019.md)
covering routing, Blueprint save/readback and PIE in NullRHI mode, plus real-editor
boundary and GUI rechecks on UE 5.8.4 and UE 5.9.0 (§6.1–§6.7 of
[capability boundaries](references/capability_boundaries.md)). Rendering, map
persistence and end-to-end public intake are outside that verified coverage.


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
  capability_boundaries.md   # can-MCP-do-X map per version + §6 rechecks + §8 isolation policy
  ue-cli-batch.md            # third layer: headless native CLI / commandlets
  ue583_baseline.json        # UE 5.8.3 toolset/tool inventory
  ue59_baseline.json         # UE 5.9.0 registry inventory
  ue57_baseline.json         # UE 5.7 placeholder, all claims [UNV]
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
