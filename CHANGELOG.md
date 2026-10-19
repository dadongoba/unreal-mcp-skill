# Changelog

All notable changes to this skill. Format: one version block per batch; the authoritative
runtime version lives in SKILL.md and domain facts live in references.

## v3.18.0 (2026-10-19)

- Client-neutral MCP server over stdio and authenticated loopback Streamable HTTP.
- Shared guarded execution/finalization for MCP and CLI; session-owned tasks.
- Published knowledge search/read tools for hosts without native Skill loading.
- Versioned shared packages, per-file manifests, checksummed releases, activation,
  active-task upgrade guards, rollback and small identical host adapters.
- Explicit candidate/reproduction/promotion workflow for community knowledge.
- Portable release workflow and cross-client/package regression coverage.

## v3.17.0 (2026-10-19)
- Independent local editor registrations and explicit target selection; instance
  and project task leases, listener identity checks, crash-released call locks.
- Shared Python JSON/SSE transport with separate sessions, negotiated protocol
  headers, tool-error detection and no blind replay of uncertain writes.
- PowerShell MCP caller delegates to Python; Python inventory/schema tools share
  instance selection and transport.
- Local experience finalization, strict allowlist schema, privacy filtering,
  opt-in original-repository Issue publishing, durable queue and reconciliation.
- A task completion wrapper journals interrupted work for recovery; unsupported
  hosts still need an explicit completion call.
- Default-branch-only Issue intake creates inbox JSON and draft PRs directly in
  dadongoba/unreal-mcp-skill; no fork, shared maintainer PAT or separate repository.
  Activation requires merging the workflow and enabling Actions PR creation.
- Smaller SKILL.md; original G-law bodies retained in references/core-workflows.md.
- Regression tests cover simulated HTTP/SSE isolation, ownership, privacy,
  idempotent publishing, intake bounds and completion recovery. Real dual-editor
  operation and live public intake are not claimed verified.

## v3.16.0 (2026-09-30)
- **Host/environment lessons batch-committed** (one 2026-09-30 session, UE 5.8.3 + RTX 3080
  10 GB / 32 GB host) - three new env-session §4 laws:
  **G21** host-memory exhaustion masquerading as GPU OOM (`D3D12Util.cpp:815`; VRAM had
  6.4 GB free while commit was full; fixes = fewer shader workers + bigger pagefile, the
  latter only via the registry - WMI `Put()` fails), **G22** `ue_connect.py wait` 420 s
  timeout != failure (SM6 first-activation load took 1136 s; poll again, do not relaunch),
  **G23** Nanite "Missing Project Settings" = missing `+D3D12TargetedShaderFormats=PCD3D_SM6`
  (first load 1136 s -> 14 s once DDC-warm).
- Plus a **G21** pointer in Common Pitfalls and the timeout clause in One-Click Connect.

## v3.15.0 (2026-09-30)
- **Development-Mode Selection law added** (router-level gate, user mandate 2026-09-30):
  for every feature request, judge C++ vs MCP/Blueprint by build+verify cost and state the
  reason *before* building - never default to MCP/Blueprint; cross-referenced from
  `references/capability_boundaries.md` §5.

## v3.14.0 (2026-09-25)
- **Full capability-boundary survey on UE 5.8.3.** New artifact
  **`references/capability_boundaries.md`** (three-axis boundary map: toolset layer /
  per-domain verdicts / substantiated absences) - now the "can MCP do X?" authority;
  `toolset_map.md` keeps the inventory role. Method: T1 static full sweep (all 52
  `describe_toolset` cached -> **830/830 tools parsed, 0 mismatch** vs the baseline; **64
  declared-limit statements** mined from Epic's own descriptions; gating map from `.uplugin`
  dependencies) + T2 read-only domain probes (~20 domains verified) + Axis C negative-space
  word-token search over all 830 tool + 52 toolset names.
- Key results: **16 UE areas covered, 8 partial, 16 absent**; zero-exposure areas include
  Landscape, Foliage, UV, Audio, Source control, Localization, Movie Render/media,
  Profiler/Insights, Virtual production, Enhanced Input, Mutable, NNE, Chooser.
- Opt-in plugin value quantified: `LiveCodingToolset` +1 tool (the only C++ compile path),
  `ChaosClothAssetToolset` +6, `MVVMToolset` +9, but **`MetaHumanGenerator` +0 and
  `SequencerAnimMixerToolset` +0** (descriptor-only stub) - so "enable the plugin" is not
  universally a capability win.
- **Official plugin pairing (§1.3/§1.4)**: `AIAssistant` (**EDA**) adds 2 editor-context
  tools (`GetProjectContext`, and `GetDockedContext` = which asset/graph the user is editing
  plus their selected nodes); plus two out-of-band official channels covering MCP blind
  spots - `CmdLinkServer` (console commands over a Windows named pipe; **enabled by
  default**) and `PythonScriptPlugin` remote execution. **Therefore the absent capabilities
  are an MCP-EXPOSURE gap, not an engine gap** - never tell a user "UE can't do X" when the
  truth is "MCP can't reach the plugin that does X".
- **New 5.8.3 trap recorded (G19)**: `find_actors.collision_channels` is declared
  `array of string` but is an ENUM array - `[]`/`[0]` work, `["WorldStatic"]` fails with a
  generic "could not convert ... to a UStruct" that never names the culprit.
- C++ boundary documented (consumption-side only: reflection/BP-binding/plugin scaffolding
  yes; source I/O, C++ class creation and compile no).
- README: EN-editor-language limitation note added (localized editor renames node families,
  so node creation by `type_id` silently fails; `culture = en` is not sufficient).

## v3.13.0 (2026-09-24)
- UE 5.8.3 tool-layer baseline re-verification: 52 toolsets / 830 tools, 0/144 broken refs,
  Pitfalls compressed under its 12 KB budget, and `refresh_schemas.ps1 -Live` fixed - it had
  never worked (PS 5.1 `Invoke-WebRequest` throws on the empty-body 202 notification reply).
- New tooling: `scripts/snapshot_toolsets.py` (all-toolset snapshot) and
  `references/ue583_baseline.json` (the frozen 5.8.3 inventory used for drift comparison).

## v3.12.0 (2026-09-11)
- **Project-open intake law**: user gives project link/name → resolve → ONE confirmation
  round with full pre-flight (path, engine, plugin audit, UE-running state; doubles as
  --fix-plugins consent) → only then launch. Never raw-shell spawn.

## v3.11.0 (2026-09-11)
- **One-Click Connect**: `scripts/ue_connect.py` (check / launch / wait / all).
  Read-only diagnosis of UE process, port-8000-vs-real-/mcp, ghost port listeners,
  .uproject plugin audit; detached launch; progress-printing wait; state cached.
  E2E-verified live: caught a real ghost process on port 8000 → launch → 289s →
  67 toolsets → all-mode reconnect 1s.
- few_shots #4 rewritten around the script.

## v3.10.0 (2026-09-11)
- **macOS twin**: cross-platform Python script twins (search_node_dict / mcp_call /
  refresh_schemas, stdlib only, BOM-safe) + `references/platform-macos.md` with §0
  platform-detection dispatch. Behavior parity with ps1 twins verified on Windows.

## v3.9.0 (2026-09-06)
- **TestT1 forensics case study** (`references/history/case_testT1_inventory.md`):
  live reconstruction of a real inventory/pickup mini-game — 7 evidence-backed
  problems (dead-cast residue, GAOC class=0, same-name call drift, CreateWidget
  Class=0, Tick-refresh antipattern, readback casing) each mapped to a fix law.
- **Web-researched gap-fill** (ue_conventions §6-§10): GAOC performance rails,
  event-driven UI refresh, widget lifecycle, overlap granularity, Map accumulate
  idiom, zh-editor display-name localization root cause. All tagged [DOC].

## v3.8.0 (2026-09-06)
- **G17 Cast-family trap**: project-BP cast ids KEEP underscores
  (CastToBP_Inventory — opposite of the cross-BP rule); locale layer (工具|Casting|)
  documented; **R27 typed-source-over-Cast pattern** (GAOC typed output) PIE-verified.

## v3.7.0 (2026-09-06)
- **G16 cross-BP battery**: create_node DOES create cross-BP nodes (naming-form
  failures were the cause); dictionary display_name ≠ tool type_id (two wrongly
  "fixed" tables reverted); R24 function signatures, R25 multi-param one-list,
  R26 target wiring, `AddEvent|UserInterface|` widget events. PIE end-to-end "42".

## v3.6.0 (2026-08-30)
- Correctness audit round: node dictionary made searchable (search_node_dict.ps1 +
  node_dict_extras.json); node_types.md contradictions fixed; refresh_schemas.ps1
  offline cross-check; verification hard rail (non-verbatim DSL write → readback
  mandatory); idempotency guards table restored.

## v3.3.0 (2026-08-29)
- Layered slim-down (35.4KB → ~14KB), capability-domain architecture (11 docs +
  router), compatibility.md weak-model fallback.

## ≤ v3.2 (2026-08-22 .. 2026-08-29)
- Origin: T1-T9 capability test rounds (58 tests), 17 verified templates, pitfall
  lawbook G1-G15, P1-P53 incident archive, AllToolsets 67-toolset survey.
