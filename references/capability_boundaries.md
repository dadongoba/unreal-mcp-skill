# Capability Boundaries — UE 5.8.3 MCP (three-axis map)

> ⚠ **VERSION SCOPE:** Everything in §0–§5 and §6.1 is the **UE 5.8.3/5.8.4** map. On **UE 5.9**
> several `[ABS]`/`[V]` verdicts are **obsolete** — console commands, file I/O, source control,
> profiler, MetaSound, Media and gameplay-ability authoring now have toolsets, and the namespace was
> fully renamed. **Read §6.3 + §6.4 before making any claim on 5.9.** Per-major baseline:
> `ue583_baseline.json` (5.8) / `ue59_baseline.json` (5.9). See §6.4's versioned-retest rule.

> **Answers "can MCP do X?" before you promise anything.** Built 2026-09-25 on UE 5.8.3
> (changelist 58210709, EN locale, CCC test bed), 52 toolsets / 830 tools.
> Inventory truth: `references/ue583_baseline.json`. Toolset landscape: `toolset_map.md`.
> Per-domain tool params: the matching `capabilities/*.md` §3.
>
> **Evidence tags** (per the skill's confidence protocol):
> - `[V]` = VERIFIED live this pass (a real call returned real data)
> - `[DOC]` = from Epic's own tool description (authoritative prose, not executed)
> - `[ABS]` = ABSENT-verified: searched all 830 tool names + 52 toolset names, no match
> - `[UNV]` = unverified / needs a target asset or a write probe (out of scope this pass)
> - `[BLOCK]` = known blocker (modal / server-killing)

## 0. TL;DR verdicts

| Question | Verdict |
|---|---|
| Can MCP read/author Blueprint graphs, components, variables? | **YES, FULL** `[V]` |
| Can MCP write C++ (source, compile)? | **NO.** Consumption-side only — see §5 |
| Can MCP edit Landscape / Foliage / UV / Modeling vertices? | **NO** `[ABS]` — Landscape+Foliage+UV=0 tools; Modeling=1 read-only tool |
| Can MCP touch Audio / Source control / Localization / Movie Render / Media? | **NO** `[ABS]` — zero tool names in all 5 areas |
| Can MCP profile the game (Insights / trace / perf)? | **NO** `[ABS]` — `trace_world` is scene raycast, not perf tracing |
| Can MCP author AnimBP state machines / montage / anim notify / IK retarget? | **NO** — Sequencer + ControlRig yes; those four no `[ABS]`+`[BLOCK]` |
| Can MCP set up networking / replication? | **NO** dedicated tools `[ABS]`; only Blueprint var-replication flags `[V]` |
| Can MCP do World Partition / data layers / HLOD? | **NO** `[ABS]` (level-instance tools exist; streaming/HLOD none) |
| Can MCP do MetaHuman / Cloth / MVVM? | **Only via opt-in plugins** — MetaHuman adds **0 tools**; Cloth +6; MVVM +9 — see §1.3 |
| Can MCP run console commands or arbitrary scripts? | **NO through MCP** — no console tool, and the Python toolset is sandboxed to `re time copy math datetime json` (no `os`) `[V]`. **But §1.4 gives two official out-of-band channels**: `CmdLinkServer` (console commands, default-enabled) and Python remote execution |
| Which plugins most improve the MCP workflow? | `AIAssistant` (EDA) for editor context; `LiveCodingToolset` for C++ compile; `ChaosClothAssetToolset`/`MVVMToolset` for new domains — §1.3 |

## 1. Axis A — Toolset layer

### 1.1 Surface
- **`bEnableToolSearch = true`** (plugin default): `tools/list` returns ONLY `list_toolsets`, `describe_toolset`, `call_tool`. Everything else is dispatched through `call_tool`. `[V]`
- **52 toolsets / 830 tools** (781 unique names). `list_toolsets` also prints 3 phantom entries that are tools, not toolsets: `GetAssetDiscoveryInfo`, `FindNiagaraScripts`, `GetNiagaraScriptDigest`. `[V]`
- Every toolset plugin ships `EnabledByDefault: false` — the live set is defined by the **`AllToolsets` aggregator's dependency list**, not by individual defaults. `[V]`

### 1.2 Gating model
Enabling a capability = adding its plugin to `.uproject` (Danger Gate #3) and restarting. `AllToolsets` covers 21 plugins → the 52 live toolsets.

### 1.3 Opt-in plugins — what enabling each actually adds `[V, from source]`

| Plugin | Adds | Verdict |
|---|---|---|
| `AIAssistant` (**EDA** — Epic Developer Assistant) | **2 tools**: `GetProjectContext()` (project/user context prompts) and `GetDockedContext()` — **which asset/graph the user is editing right now, plus their selected nodes**. Deps: PythonScriptPlugin, EditorScriptingUtilities, ToolsetRegistry | ⭐ **Highest DX value** — the editor-context channel an external agent otherwise lacks |
| `LiveCodingToolset` | `CompileLiveCoding()` — triggers an incremental Live Coding compile, returns status + LogLiveCoding + UBT diagnostics (needs Live Coding enabled in Editor Preferences) | **The only C++ compile path via MCP** |
| `ChaosClothAssetToolset` | 6 tools: `CreateClothingAsset`, `AssignClothingToSection`, `RemoveClothingFromSection`, `ListClothingAssets`, `GetSectionClothing`, `ConvertClothingAssetCommonToChaosClothAsset` | Real new domain (cloth) |
| `MVVMToolset` | 9 tools: `CreateViewModel`, `AddViewModelProperty`, `ListViewModels`, `ListWidgetViewModels`, `AddViewModelToWidget`, `ListWidgetViewBindings`, `RemoveWidgetViewBinding`, `CreateViewBinding`, `ListConversionFunctions` | Real new domain (MVVM binding) |
| `MetaHumanGenerator` | **0 MCP tools** — its only exports (`ResetNeckToBody`, `IsOptionalContentInstalled`) are `BlueprintCallable`, NOT `AICallable` | ⚠ Name promises more than it delivers |
| `MCPClientToolset` | **0 toolsets by design** — it is an adapter letting registry consumers reach local/private MCP servers | Not a capability add |
| `SequencerAnimMixerToolset` | **0 toolsets** — descriptor-only stub (no `Modules` array, no `Source/`), depends on `MovieSceneAnimMixer` | Empty shell |

> Found by scanning **every** `.uplugin` under `Engine\Plugins` for `AICallable` — not just the
> `Experimental\Toolsets\` folder. `AIAssistant` is the only provider found outside that folder.
> `MCPClientToolset`'s own description names **"the EDA"** as a toolset-registry consumer, so
> `AIAssistant` + `MCPClientToolset` is Epic's intended in-editor-assistant ↔ MCP stack.

### 1.4 Complementary official channels (NOT MCP tools — they cover MCP's blind spots)

MCP itself can neither run console commands nor run unsandboxed Python (§4.1). Two official
channels cover those gaps **out of band**: `[V, from source]`

| Channel | Covers | Evidence |
|---|---|---|
| **`CmdLinkServer`** (`EnabledByDefault: true`, Win64, PostDefault) | **Console command execution** | Description: "Listens to and runs console commands from CmdLink". Impl: `FPlatformNamedPipe` (Windows named pipe), an `OnKeyChanged` auth key, and `Begin/AbortAsyncCommand` for multi-frame commands. ⚠ No CmdLink **client** ships in `Engine\Binaries` — an external tool is required |
| **`PythonScriptPlugin` remote execution** | **Arbitrary Python** (no sandbox) | Setting `bRemoteExecution`; defaults multicast `239.0.0.1:6766`, bind `127.0.0.1`, TTL `0` (localhost only). Plus `StartupScripts` and `bDeveloperMode` (generates Python stubs for IDE autocomplete) |
| `EditorScriptingUtilities` | Python editor-API breadth (also an EDA dependency) | declared dependency of `AIAssistant` |

**Consequence for §3 and §4.1 — the gaps are in the MCP EXPOSURE layer, not in the engine.**
Official engine plugins exist for UV (`UVEditor`), landscape (`LandscapePatch`), modeling
(`GeometryMode`, `ModelingToolsEditorMode`, `StaticMeshEditorModeling`, `MeshLODToolset`),
movie render (`MovieRenderPipeline`), retargeting (`IKRig`), EQS (`EnvironmentQueryEditor`),
localization (`Localization`) and source control (`ChangelistReview`) — **none expose MCP tools
today**. Where a script/console channel is reachable those features become indirectly drivable;
where it is not, they are unreachable for an agent. Do not tell a user "UE can't do X" when the
truth is "MCP can't reach the plugin that does X".

## 2. Axis B — Per-domain capability matrix

Status legend: **FULL** (read+write) · **READ** (read verified, writes untested) · **PARTIAL** · **NONE** · **BLOCK** · **UNV** (needs a target asset).

| UE domain | Status | What works | What doesn't | Ev |
|---|---|---|---|---|
| Blueprint graphs / DSL | FULL | create BP, components, variables, event+fn graphs, DSL write/readback, compile, cross-BP calls, pin surgery, `get_graph_dsl_docs` | — | `[V]` |
| Scene / actors / levels | FULL | `get_current_level`, `find_actors`, transforms, folders, outliner ops, level instances | see §4.2 enum-array trap | `[V]` |
| Assets | FULL | find / class / duplicate / move / delete / save / metadata / folders | — | `[V]` |
| Static & skeletal mesh | FULL | LOD count, bones, morphs, sockets, physics-asset read, collisions, Nanite toggle, vertex count | no vertex/edge-level mesh editing | `[V]` |
| Materials / textures | FULL | material + instance graphs, params, expressions, texture size | no TextureGraph authoring | `[V]` |
| UMG / widgets | FULL | widget BP create/compile, widget classes, slots, bindings | MVVM binding needs opt-in plugin | `[V]` |
| Data assets / tables / curves / strings | FULL | table/curve/string/DataAsset CRUD, file import | import shape gates — see §4.4 | `[V]`/`[DOC]` |
| Editor app / viewport / PIE | FULL | PIE start/stop, capture, camera, selection, content browser | `FocusOnActors` refuses during PIE `[DOC]` | `[V]` |
| Logs / config / plugins | FULL | log query+verbosity, config sections read/write, plugin list/enable/deps, plugin create from template | — | `[V]` |
| Slate / editor UI automation | FULL | `Observe`→`Snapshot`→`Click`/`FillForm`/`PressKey` | UE native modal boxes ignore synthetic clicks — §4.3 | `[V]` |
| Sequencer / cinematics / keyframes | FULL | sequence→bind→track→section→keys→FBX export, ControlRig posing/keying, anim layers | pose readback still 0.0 — §6 | `[V]`+`[UNV]` |
| Niagara VFX | FULL | system/emitter/module/renderer authoring, topology, script discovery | — | `[V]`(skill)+`[DOC]` |
| Physics / collision | FULL | runtime sim activation, constraints, collision profiles, raycast | destruction/fracture/geometry-collection not exposed | `[V]` |
| PCG | FULL | graph create/node/graph-instance/spawn/execute, native-node list, graph structure read | one-actor-at-a-time rule — §4.5 | `[V]` |
| Dataflow | FULL | compatible asset types, templates, graph editing | — | `[V]` |
| GAS | READ | attribute sets, gameplay cues, ability system inspection | no ability authoring | `[V]` |
| Automation tests | FULL | discover/list/run/status/results/stop | `DiscoverTests()` MUST run first `[DOC]` | `[DOC]` |
| AI: BehaviorTree / StateTree | READ | inspection tools live | no target assets here → authoring `[UNV]` | `[V]` |
| Conversation / WorldConditions | READ | description/inspection | no target assets → `[UNV]` | `[DOC]` |
| Animation authoring (AnimBP/state machine/montage/notify/IK retarget) | **NONE** | — | 0 tools by name search; AnimBP create is refused at the tool layer | `[ABS]`+`[BLOCK]` |
| Level Blueprint editing | PARTIAL | needs manual open-once first | post-open behaviour `[UNV]` | `[DOC]` |
| Modeling Mode (vertex/edge) | **NONE** | `get_vertex_count` (read-only) | no extrude/bevel/boolean/polygroup | `[ABS]` |
| Landscape / terrain sculpt+paint | **NONE** | — | 0 tools | `[ABS]` |
| Foliage / vegetation | **NONE** | — | 0 tools | `[ABS]` |
| UV editor / unwrap | **NONE** | — | 0 tools | `[ABS]` |
| Audio (cues/submix/attenuation/MetaSound) | **NONE** | — | 0 tools | `[ABS]` |
| Source control (checkout/submit/revision) | **NONE** | — | 0 tools | `[ABS]` |
| Localization | **NONE** | — | 0 tools | `[ABS]` |
| Movie Render Queue / media / video | **NONE** | — | 0 tools | `[ABS]` |
| Profiler / Insights / trace | **NONE** | — | 0 tools (`trace_world` is a scene raycast) | `[ABS]` |
| Networking / replication / RPC | **NONE** | only BP `get/set_variable_replication` flags | no replication setup, no RPC authoring | `[ABS]` |
| World Partition / data layers / HLOD | **NONE** | level-instance create/edit/commit only | no streaming, no data layers, no HLOD | `[ABS]` |
| Nanite / Lumen / post-process / lighting | **PARTIAL** | `is_nanite_enabled` / `set_nanite_enabled` | no Lumen, lights, or post-process authoring | `[ABS]` |
| Enhanced Input | **NONE** | — | no input-asset tools; key events only via hand-built Blueprint nodes | `[ABS]` |
| Virtual production (nDisplay / Live Link) | **NONE** | — | 0 tools | `[ABS]` |
| Mutable / NNE / Chooser | **NONE** | — | 0 tools | `[ABS]` |
| MetaHuman | **NONE** | — | plugin ships 0 `AICallable` tools | `[V]` |
| Cloth | **NONE** (default) | — | opt-in plugin adds 6 | `[V]` |
| MVVM | **NONE** (default) | — | opt-in plugin adds 9 | `[V]` |

## 3. Axis C — Not exposed, with search evidence

Absence claims are substantiated by the §2 search: the token set was checked against all 830
tool names AND all 52 toolset names (CamelCase + snake_case tokenised, exact word match — a v1
substring scan produced false hits like `nne` inside `coNNEct` and missed `behavior_tree` vs
`BehaviorTreeTools`, so the method was corrected before any verdict was recorded).

Zero-match areas (no tool and no toolset): **Landscape, Foliage, UV editor, Audio, Source control,
Localization, Movie Render Queue/media, Profiler/Insights, Virtual production, Mutable, NNE,
Chooser, Enhanced Input**.

Single-digit partials: Modeling Mode (1 read tool), splines (`DrawSpline` only), render settings
(Nanite toggle only), networking (BP replication flags only).

## 4. Cross-cutting laws (systematic boundaries)

### 4.1 No file I/O, no shell, no console
The Python scripting toolset's sandbox is exactly `{re, time, copy, math, datetime, json}` —
no `os`, no `unreal`, no file writes `[V]`. There is no console-exec tool (`SearchCVars` only
searches). **So nothing reachable THROUGH MCP can edit source files, run a build, or invoke an
external process.** Note the scope: that is an MCP-surface limit, not an engine limit — see §1.4
for the official out-of-band channels (`CmdLinkServer` console commands, Python remote execution)
that bypass the tool layer entirely.

### 4.2 ⚠ Enum arrays: the schema lies, and the error doesn't name the parameter `[V]`
`SceneTools.find_actors.collision_channels` is declared `"type": "array", "items": {"type": "string"}`
— but at runtime it is an **enum array**:
- `[]` works (all channels) · `[0]` works (numeric enum index) · `["WorldStatic"]` **FAILS** · `["ECC_WorldStatic"]` **FAILS**
The failure is a generic `could not convert incoming function input params Json to a UStruct` that
does **not** name `collision_channels` — so it reads like a malformed whole-request error.
**Rule: when a "string array" param fails conversion, try numeric enum indices or an empty array.**
Expect the same for other enum-array params not yet catalogued.

### 4.3 Modal blockers
`BlueprintTools.create(asset_type=/Script/Engine.AnimBlueprint)` hangs the MCP server (skeleton-picker
modal) — the editor stays alive but MCP is dead until the dialog is dismissed. Dismiss with
`PostMessage WM_CLOSE` to `FindWindow(NULL,"Message")`; UE's own modal boxes ignore synthetic clicks
(`references/screen_control.md`). `[BLOCK]`

### 4.4 Declared gates on import/lookup tools `[DOC]`
- `DataTableTools.import_file` — columns must match the schema struct's property names
- `StringTableTools.import_file` — header row must contain `Key` and `SourceString`
- `CurveTableTools.import_file` — `interp_mode` must be `RCIM_LINEAR` or `RCIM_CONSTANT`
- `DataRegistryTools.GetItems` — only returns items already in the registry cache
- `NiagaraToolset_Assets.FindNiagaraScripts` — "no way to discover non-exposed versions through the asset registry"

### 4.5 Serialization requirements (do not parallelise these) `[DOC]`
- `PCGToolset.GetNodeDataView` / `ExecuteGraphInstance` — when several actors share a graph, call on
  **one actor at a time** and wait for completion before the next
- `SceneTools.edit_level_instance` — **only one level instance may be in edit mode at a time**
- `AutomationTestToolset` — `DiscoverTests()` must complete once before any list/run/status call

### 4.6 Ordering / recompile gates
`BlueprintTools.set_parent` and `retarget_node_class` both require a Blueprint recompile afterwards;
`get_default_object` reads a stale CDO until the Blueprint is compiled. `[DOC]`

### 4.7 PIE-conditional tools
`EditorAppToolset.FocusOnActors` **cannot be called while PIE is active** `[DOC]`.
`GameplayCueToolset.ExecuteCueOnSelectedActor` needs a PIE session or a configured cue manager to
show anything `[DOC]`.

### 4.8 Event-dispatcher parameter limit
`add_function_param` / `add_object_function_param` / `add_struct_function_param` / `remove_function_param`:
**output parameters are not supported on event dispatchers** `[DOC]`.

## 5. C++ boundary (consumption, not production)

> **Mode choice comes first.** A feature may be cheaper in C++ than via MCP/Blueprint (or vice
> versa) — see SKILL.md "Development-Mode Selection" before assuming MCP. This section states what
> a C++ path *costs* (produce outside MCP, consume inside), not whether C++ is the right path.

| Capability | Status |
|---|---|
| Runtime reflection of C++ types (`search_subclasses` returns `/Script/Engine.*` classes) | **YES** `[V]` |
| Call C++ `UFUNCTION`s from graphs (all `Math\|`, `Actor\|`, `Game\|`, `Transformation\|` categories are C++) | **YES** `[V]` |
| Blueprint ↔ C++ binding: `create(asset_type=/Script/Module.Class)`, `set_parent`, `get_parent` | **YES** `[V]` |
| Scaffold a C++ plugin from a template (`CreatePlugin`; templates are C++: Blank / Blueprint Library / Editor Mode / Third Party Library) | **YES** `[V]` |
| Read/write `.h`/`.cpp` | **NO** — no file I/O (§4.1) |
| Create a C++ class (editor "New C++ Class" wizard) | **NO** — not exposed |
| Compile C++ (UHT regeneration, incremental or full) | **NO by default** — only via opt-in `LiveCodingToolset.CompileLiveCoding()` |
| Full/clean build | **NO** — external `Build.bat` with UE closed (`templates/cpp_workflow.txt`) |

**Practical shape**: C++ work is two-phase — *produce* outside MCP (file tools + UBT), *consume*
inside MCP (bind, call, verify in PIE). Enabling `LiveCodingToolset` closes the incremental-compile
gap only.

**But the "NO"s above are MCP-surface limits, not engine limits.** Both rows marked NO are
reachable through the §1.4 channels: UE's embedded Python is a **real, unsandboxed CPython**
(only MCP's `ProgrammaticToolset` is restricted), so Python executed via remote execution — or via
the `py <script>` console command through `CmdLinkServer` — can read/write files and, by the same
argument, shell out to UBT for a full build. `[UNV, inferred from the plugin settings — not
executed this pass]` Treat §1.4 as the escape hatch whenever a task hits an MCP-surface NO.

## 6. Open items (explicitly unresolved)

| Item | Why unresolved |
|---|---|
| `SemanticSearchToolset` Search struct shape | declared params don't match the accepted struct; never converted successfully |
| ControlRig pose readback | every authoring call succeeds but pose reads back 0.0 — evaluation linkage unknown; **verify visually before promising animation** |
| `PhysicsAssetTools.CreateFromMesh` | needs a real `physicsAsset` object (param is object-typed); no such asset in the test bed |
| AnimBP EventGraph authoring | `[UNV]`; AnimBP *creation* is `[BLOCK]` |
| BehaviorTree / StateTree / Conversation / WorldConditions authoring | only inspection verified; no target assets in the test bed |
| Enum-array params beyond `collision_channels` | only one catalogued; systematic survey needs write probes |
| Opt-in plugin toolsets (LiveCoding/ChaosCloth/MVVM) | tool inventories read from source; never executed — `[UNV]` |

### 6.1 Recheck 2026-11-23 — CCC, UE 5.8.4-EN (live MCP, task-leased)

Question asked: "now that AI is stronger, do these UNV items still stand?" Answer: **AI strength is
irrelevant here — an UNV clears only when its *condition* is met (asset / plugin / working endpoint).**
Live editor was launched on CCC (PID-leased, port 8000, 52 toolsets — matches baseline) and each
item probed. Results:

| Item | 2026-11-23 result | Tag |
|---|---|---|
| `PhysicsAssetTools.CreateFromMesh` | **Root cause GONE.** Schema now `meshPath:string` + `bAssignToMesh:bool` (NOT object-typed as the old note said). Fake path `/Game/__PROBE__/DoesNotExist` returned *"No skeletal mesh found at ..."* → params parse + reach engine logic. Real assets exist (`SK_Crow`). Only the actual create-and-save (a disk write) was intentionally not performed. | `[VERIFIED 2026-11-23 UE5.8.4-EN]` schema+params; full create still `[UNV]` by choice (write) |
| PhysicsAsset object-ref reads (`GetBodyNames`) | **CLEARED.** `physicsAsset:{"refPath":"/Game/TestT13/Crow/Meshes/SK_Crow_PhysicsAsset..."}` returned 19 body names. Object-typed params work with `refPath` form. | `[VERIFIED 2026-11-23 UE5.8.4-EN]` |
| `SemanticSearchToolset.Search` struct | **Partly cleared.** `{"query,classFilter:[],pathRegexes:[],k}` now *converts* (old note "never converted successfully" no longer holds) — reaches backend and fails with *"Embedding generation failed: Connection failed"*. Struct accepted; a live embedding service is the new blocker. | `[VERIFIED 2026-11-23 UE5.8.4-EN]` struct accepted; result still blocked (no embedding backend) |
| ControlRig pose readback | **Still UNV — condition unmet.** `get_all_controls`/`get_all_bones` returned `[]` on `CR_Test`/`CR_Test13` (no built hierarchy). `get_local_transform` with empty item ref returns identity (0,0,0 / scale 1) — expected for a null item, NOT evidence about pose. Need a CR asset with a real hierarchy to test the original 0.0-readback claim. | `[UNV]` (asset prerequisite missing) |
| StateTree authoring | **Still inspection-only.** `StateTreeTools` = 9 getters, no authoring tools by schema. `get_root_states` on `ST_Test` returned *"not valid StateTree"* (asset path/class mismatch). Authoring remains absent at the tool layer. | `[UNV]` / effectively absent |
| BT / Conversation / WorldConditions authoring | **Unchanged.** Toolsets present, inspection-only by schema; no target assets in CCC. | `[UNV]` |
| AnimBP EventGraph authoring | **Unchanged.** No AnimBP asset; creation still `[BLOCK]` (skeleton-picker modal). | `[BLOCK]` |
| Enum-array params beyond `collision_channels` | **Unchanged** — needs systematic write probes; not run this pass. | `[UNV]` |
| Opt-in toolsets (LiveCoding/ChaosCloth/MVVM) | **Unchanged.** `LiveCodingToolset` describe returned *"toolset not found"* on CCC — plugins not enabled in `.uproject` (matches §1.3 gating). | `[UNV]` (plugin gating) |

**Meta-verdict**: 2 items cleared, 1 structurally advanced (struct accepted, new external blocker),
5 unchanged because their *prerequisite* (asset/plugin/write-probe) is still absent. Not one changed
because the model got smarter — they changed because the **engine schema, test-bed assets, or
runtime config** changed. This is the operational proof of why the re-verification protocol (§7)
diffs tools/assets, not "AI capability".

### 6.2 OPEN QUESTION — Level Blueprint "cannot open" vs Codex claim (2026-11-23) `[UNV — NEXT ITERATION]`

**Status: unresolved — contradictory reports, do NOT close.** This is a scheduler note for the next
iteration, not a conclusion. Recorded because two observations conflict and neither was fully reproduced.

- **Claim (user report):** "Codex opens the level blueprint every time and goes straight in to do
  functional design." If true, the G9/#47 `needs manual open-once first` note is either outdated or
  circumventable, and §1 table row "Level Blueprint editing | PARTIAL" needs upgrading.
- **Contradicting evidence (this session, UE 5.8.4, CCC `/Game/TestT1/NewMap`):**
  - Offline Python (`-run=pythonscript`): asset registry reports **0** `LevelScriptBlueprint` assets;
    `load_object` on 4 candidate ref paths → all `None`. `new_object(LevelScriptBlueprint)` *does*
    create an object but it is a hollow shell — `ubergraph_pages`/`graphs`/`generated_class`
    unreadable, no EventGraph, not attached to `Level` (whose `LevelScriptBlueprint` property is
    protected). `Level`/`World` expose no `get_level_script_blueprint` (C++ `ULevel::GetLevelScriptBlueprint`
    exists but is not Python-exposed).
  - Live MCP (task-leased): before any manual open, `BlueprintTools.get_graph` on 4 candidate refs →
    all `not valid Blueprint`. `EditorAppToolset.OpenEditorForAsset` rejects blueprint refs
    (`not a valid asset path`); the map path opens but `GetOpenAssets` stays empty and the graph is
    still unreadable. `SlateInspector` observed one window ("CCC - Unreal Editor") but `Snapshot`
    returned ~209 bytes with no widget tree (unfocused/headless state) — **the UI-click route was
    NOT actually reproduced**.
- **Working hypothesis (unproven):** Codex does not use a direct API — it likely drives
  `SlateInspectorToolset` (Observe→Snapshot→Click) to click the toolbar Blueprint button / content
  browser, which performs the G9/#47 "open once" and instantiates the object. If so, the capability
  is "agent clicked the UI", not "AI got stronger" and not "MCP gained an API".
- **Next iteration — concrete test plan (do all three):**
  1. Obtain one real Codex operation record (tool calls / screenshots). Identify the exact tool and
     click target. If unavailable, reproduce manually: with a **focused** editor window, `Windows`
     → `Observe(ref="")` → `Snapshot`, locate the level-Blueprint entry, `Click` it.
  2. After open, call `EditorAppToolset.GetOpenAssets` (expect the blueprint to appear) then
     `BlueprintTools.get_graph(blueprint=<ref>, graph_name="EventGraph")` /
     `read_graph_dsl`. If both work → upgrade §1 row from PARTIAL `[DOC]` to
     `[VERIFIED <date> UE<ver>-<lang>]` and append the click recipe to `core-workflows.md` G9/#47.
  3. If Snapshot still returns an empty tree, try `Observe` on a specific `ref` (not `""`) and a
     window `select` via `Windows(action="select")` first. An empty tree is a harness limitation,
     **not** proof the UI route fails.
- **Guard:** do NOT "resolve" this by reasoning about model capability. Resolve it by reproducing
  the exact tool call, exactly as §7 diffs tools/assets rather than rating "AI strength".

### 6.3 UE 5.9.0 recheck on real machine (2026-11-23) `[VERIFIED 2026-11-23 UE5.9.0-EN]`

Engine `E:\UE_5.9` (5.9.0, CL 60738873), read-only commandlet probes via a module-free probe
project `CCC59Probe.uproject` sharing CCC/Content. Method: `-AgentMode -nullrhi -run=pythonscript`
with a script that writes results to disk (stdout `print` is not reliable). Exit 1 was caused by
unrelated project plugin/build baggage, not by the probe; every probe reached `=== DONE ===`.

**Toolset layer doubled — authoritative registry snapshot (`ToolsetRegistry.get_all_toolset_json_schemas()`,
2.85 MB JSON): 106 registered toolsets on 5.9 vs 52 observed on 5.8.4.**

| Earlier verdict | 5.9 finding | Action |
|---|---|---|
| StateTree authoring `[UNV]` (inspection-only) | `state_tree_toolset.state_tree.StateTreeToolset` has **49 tools**, full authoring: `add_task`, `add_blueprint_task`, `add_evaluator`, `add_consideration`, `add_global_task`, `move_*`, `remove_*`, `get_*` | **CLEARED** — authoring now exists |
| BehaviorTree authoring `[UNV]` | `AIModuleToolset.BehaviorTreeToolset` has **25 tools**: `CreateBehaviorTree`, `AddComposite`, `AddTask`, `AddDecorator`, `AddService`, `AddBlackboardKey`, `Move*/Remove*` | **CLEARED** — authoring now exists |
| SemanticSearch `[UNV]` (struct never converted / embedding backend down) | `SemanticSearchToolset` **absent** from 5.9 registry | Boundary moved: tool removed, not fixed |
| opt-in LiveCoding/Cloth/MVVM `[UNV]` | `LiveCodingToolset`, `ChaosClothAssetToolset`, `MVVMToolset` all registered | **CLEARED** at registry level; execution still untested |
| Python DSL we document | Official `BlueprintToolsets.BlueprintDslToolset` (7 tools: `Read`/`Write`/`Edit`/`Diff`/`Schema`/`Docs`/`FindNodeReferences`) + `editor_toolset.toolsets.blueprint.BlueprintDslTools` | Our DSL is now official; prefer native toolset on 5.9 |
| Skill mechanism we document | `ToolsetRegistry.AgentSkillToolset` (4 tools: `ListSkills`/`GetSkills`/`CreateSkill`/`UpdateSkill`); Markdown `SKILL.md` folders under `<Plugin>/Skills/`, `<Project>/Skills/`, `Engine/Extras/AgentTools/Skills/` with frontmatter `name`/`description`, loaded by `GetSkills`, relative links rewritten to absolute | Architecture validated; our external package may be superseded on 5.9 |
| `FileSystemToolset`, `ConsoleToolset`/`LogsToolset`, `PerfToolset` (Csv/Gpu/Stats), `SceneCaptureToolset`, `WidgetAnimationToolset`, `TextureGraphToolset`, `FabToolset` | all newly registered | Re-run §1 axis-A inventory on 5.9 before claiming any `[ABS]` |

**13-domain `[ABS]` claims: still mostly intact.** No toolsets for Landscape, Foliage, UV, Audio,
Localization, Movie Render. `SourceControl` exposes only `SourceControlHelpers` (not editing
source control state). Profiler now has `CsvProfilerToolset`/`GpuProfilerToolset`/`StatsToolset`
— profile **inspection** is no longer ABS, but profiler-driven automation is untested. As always,
re-diff the tool inventory (§7) rather than assuming.

**Level Blueprint (§6.2) — partially advanced, NOT closed:**

- 5.9 Python still exposes **no** `get_level_script_blueprint` on `Level` or `World` (both report
  `relevant: []`), and `AssetRegistry` still reports 0 `LevelScriptBlueprint` assets. The G9/#47
  lazy-object root cause **survives 5.9**.
- New in 5.9: `unreal.BlueprintEditorLibrary` (143 methods, incl. `find_event_graph`,
  `list_graph_names`, `create_node_from_reference`, `create_entry_point`, `compile_blueprint`) and
  `GraphDsl*` structs. On a `new_object(LevelScriptBlueprint)` shell: `find_event_graph` → `None`,
  but `add_function_graph(lb,"ProbeGraph")` **succeeded**, `list_graph_names` → `['ProbeGraph']`,
  and `create_node_from_reference(g,"KismetSystemLibrary.PrintString",...)` **created a real
  `K2Node_CallFunction`**. So 5.9 can inject a graph/node into the shell — something 5.8.4 could not.
- **But** `compile_blueprint` → `False`, `generated_class` → `None`, `create_entry_point` → `None`.
  The shell is still not a runnable level blueprint. Programmatic authoring is partial; the
  §6.2 open question stays `[UNV — NEXT ITERATION]`, now with this new evidence attached.
- **Codex claim explained by official docs:** UE 5.9 `Unreal Assistant` panel runs Claude Code /
  Codex / Cursor / OpenCode via **Agent Client Protocol (ACP)** adapters (`codex-acp`,
  `claude-agent-acp`) and connects them to the same Unreal MCP server; every tool call is visible
  in the panel's **Required Actions**. MCP server is loopback-only, no auth. So Codex and our
  agent use the *same* tools — the difference is which actions it performs (likely Slate UI click
  → open-once), not model strength. A future iteration can obtain the exact call chain from
  Required Actions.

**5.9 headless-run knowledge is now official:** engine ships
`Engine/Extras/AgentTools/Skills/unreal-headless-run/SKILL.md` documenting `-AgentMode`
(`-unattended -nosplash -nopause`, JSON stdout, auto-dismiss dialogs), `-ExitTimeout`/`-NoProgressTimeout`/
`-HangTimeout` (exit 124/125/126), `<Project>/Saved/Logs/<exe>-<pid>.result.json` with
`exit_code`/`reason`/`markers`/`suppressed_dialogs`, and Git Bash argument-mangling traps
(`MSYS_NO_PATHCONV=1`). Our `ue-cli-batch.md` remains useful for 5.8.4 and for the
MCP-vs-CLI-vs-knowledge routing decision, but on 5.9 prefer the native skill.

**Harness notes (learned the hard way):** GUI editor launched with `-nullrhi` hangs at
`Running DelayedAutoRegister Phase` with no log progress; GUI needs rendering, commandlet does not.
A probe `.uproject` placed inside CCC/ still triggers UBT to compile `CCCEditor.Target.cs` and
fails on the Chinese path (`C1083` PCH missing) + stale `UELink` BuildId — keep probes module-free
and in a clean directory. Registry snapshots can be taken without any GUI via commandlet Python.

### 6.4 Full 5.9 boundary re-check — all 5.8 axes + new ground (2026-11-23) `[VERIFIED 2026-11-23 UE5.9.0-EN]`

§6.3 was a partial recheck. This pass re-runs **every 5.8 axis** against the 5.9 registry and adds
live execution probes. Sources: authoritative 106-toolset / 1872-tool JSON snapshot
(`ue59_baseline.json`, captured via `ToolsetRegistry.get_all_toolset_json_schemas()`),
normalized 5.8↔5.9 diff, and commandlet Python calls via `ToolsetRegistry.execute_tool`.

**Methodology correction (applies to every future diff):** 5.9 renamed the whole namespace —
`editor_toolset.toolsets.actor.ActorTools` → `EditorToolset.ActorToolset`, snake_case → PascalCase.
A raw name diff reports a false 82 added / 28 removed toolsets and 1872/781 disjoint tool names.
Normalize by **strip-non-alphanumeric + lowercase on the short name** before diffing:
canonical tools 5.8=774 / 5.9=1708, kept 615, dropped 159, new 1093. Even then, "dropped" tools
like `set_transform`/`find_actors` still exist under PascalCase (`ActorToolset.SetActorTransform`,
`LevelToolset.FindActors`) — **confirm by domain re-search, never declare a capability lost from a
name diff alone.** Also "106 vs 52" is not apples-to-apples: 52 was the live `AllToolsets` set on
5.8.4, 106 is the full registry on 5.9.

**Live-call protocol for `ToolsetRegistry.execute_tool` (proven this pass):**
`execute_tool(toolset_name, tool_name, json_input)` — toolset must be the **full dotted name**
(`ConsoleToolset.ConsoleToolset`), tool the **short name** (`GetCVarValue`), params the schema keys
from `inputSchema.properties`; result is `AsyncFunctionResultString`: call
`get_value_as_json_string()` for the JSON payload, read `.error` for a structured failure (the error
lists valid params / closest tool names — use it to self-correct). A short toolset name yields
"Toolset 'X' not found. Closest registered toolsets: ...". Direct `unreal.<Toolset>.<snake_case>()`
Python calls do **not** work on these toolsets.

**Axis A — `[ABS]`/`[V]` verdicts broken on 5.9 (live-executed unless noted):**

| 5.8 verdict | 5.9 reality | Evidence |
|---|---|---|
| §4.1 "no console tool / no console commands" `[V]` | **FALSE.** `ConsoleToolset.RunConsoleCommand` executed `stat unit` → `{"returnValue":["Cmd"]}`; `GetCVarValue(r.ScreenPercentage)` → `"0"`; `SearchCVars` returns the cvar table | `[VERIFIED 2026-11-23 UE5.9.0-EN]` live |
| §4.1 "no file I/O through MCP" `[V]` | **FALSE.** `FileSystemToolset` = 9 tools (ReadTextFile/WriteTextFile/CreateDirectory/DeleteFile/ListDirectory/ResolvePath/EditTextByAnchor/EditTextByLineRange/**DownloadUrl**). `ListDirectory` executed OK; `ReadTextFile` reached its validator (`FirstLine must be ≥ 1` — pass `firstLine=1`) | `[VERIFIED ...]` live read; write/download not executed |
| §3 "Source control = 0 tools" `[ABS]` | **FALSE.** `SourceControl.SourceControlHelpers` = 38 tools: CheckOut, CreateChangelist, SubmitChanges, SubmitChangelist, ListAssetRevisions, LoadAssetRevision, diff changelists… `GetAssetSourceControlState` reached engine ("Revision control is not enabled" — CCC has no provider) | `[VERIFIED ...]` tool present + engine-reached |
| §3 "Profiler/Insights = 0" `[ABS]` | **FALSE.** `PerfToolset.CsvProfilerToolset`(5)/`GpuProfilerToolset`(1)/`StatsToolset`(4) + `RewindDebuggerToolset`(10) | registry `[VERIFIED ...]`; execution untested |
| §2 "Movie Render / media / video = 0" `[ABS]` | **PARTLY FALSE.** `MediaToolset.MediaToolset` = 4 tools registered; Movie Render itself still has no toolset | registry `[VERIFIED ...]` |
| §2 "Audio = 0" `[ABS]` | **PARTLY FALSE.** `EditorToolset.SoundWaveToolset`(2) + `MetaSoundToolset` = 42 tools (Authoring 24 / Discovery 5 / Inspection 13). §6.3's `FindMetaSoundAssets` was a substring false hit — real discovery tools: `FindNodeClasses`/`FindDataTypes`/`FindInterfaces`/`FindRegisteredPages` | registry `[VERIFIED ...]` |
| §2 "World Partition / data layers / HLOD = 0" `[ABS]` | **PARTLY FALSE.** `LevelToolset` has AddActorsToDataLayer/GetDataLayers/CreateDataLayerAsset/… (data layers reachable); HLOD/streaming still absent | registry `[VERIFIED ...]` |
| §2 "Animation authoring = NONE" `[ABS]`+`[BLOCK]` | **Still ABS at tool level** — no AnimBP/state-machine/montage/notify/IK-retarget toolset (ControlRig/Sequencer authoring is separate and large) | `[VERIFIED ...]` |
| §3 Landscape / Foliage / UV / Localization / Virtual production / Mutable / NNE / Chooser / Enhanced Input / Modeling-mode / destruction | **still 0 toolsets** — `[ABS]` survives 5.9 | `[VERIFIED ...]` |
| §2 GAS "READ, no ability authoring" | **UPGRADE.** `GASToolsets.GameplayAbilityToolset.CreateGameplayAbility` exists; `AttributeSetToolset`/`GameplayCueToolset` present | registry `[VERIFIED ...]`; execution untested |
| §2 AI "BT/StateTree READ-only" | **UPGRADE — confirmed again.** `state_tree_toolset…StateTreeToolset` 49 tools (authoring), `AIModuleToolset.BehaviorTreeToolset` 25 (`CreateBehaviorTree`/`AddComposite`/`AddTask`/`AddBlackboardKey`…) | registry `[VERIFIED ...]` |
| §6.1/§6.3 SemanticSearch | **CONFIRMED GONE** — no `SemanticSearchToolset` in 5.9 registry | `[VERIFIED ...]` |
| — new — `ToolsetRegistry.AgentSkillToolset` | 4 tools; `ListSkills` executed OK, returned engine built-in skills (ChaosClothAssetConversionSkill, DataflowGraphEditingSkill, PCGSkill…) | `[VERIFIED ...]` live |
| — new — `editor_toolset.toolsets.python_scripting.PythonScriptingTools` | 4 tools (`execute_python`/`get_symbol`/`read_me`/`search_symbols`) — a tool-layer Python path distinct from §1.4 remote exec | registry `[VERIFIED ...]`; sandbox scope untested |
| — new — `FileSystemToolset.DownloadUrl` | network fetch exposed as an MCP tool | registry `[VERIFIED ...]`; NOT executed (untrusted I/O) |

**Axis B / C verdict:** the 5.8 "NO" rows for console/file-I/O/source-control/profiler/media/
MetaSound/gameplay-ability are obsolete on 5.9 — they describe the **5.8 exposure layer**, not UE.
Persistent gaps (Landscape, Foliage, UV, Localization, nDisplay/LiveLink, Enhanced Input, AnimBP
authoring, vertex modeling, destruction, NNE/Chooser) are unchanged. Keyword re-search produced
false positives (`link`→`SetWidgetAnimationDisplayLabel`, `net`→`MovieSceneTimeWarp`, `nne`→`connect`)
— every candidate MUST be confirmed against the actual toolset list, as done above.

**5.8 cross-cutting laws (§4.2–§4.8) — NOT re-executed this pass.** This pass re-tested the
*capability surface* (does a tool/domain exist and can it be called), not the *behavioural traps*:
§4.2 enum-array schema-lies, §4.3 skeleton-picker modal, §4.4 import shape gates, §4.5
serialization rules, §4.6 recompile gates, §4.7 PIE-conditional tools, §4.8 event-dispatcher param
limit were NOT re-probed on 5.9 and keep their 5.8 tags. Note §4.1's conclusion ("no file I/O /
no console") *is* explicitly overturned above. Before relying on a §4 law on 5.9, re-run the
specific write probe; the namespace/param renames alone mean cached signatures are stale. §5
C++ boundary likewise: file I/O is now reachable via `FileSystemToolset` (overturning its "NO
read/write .h/.cpp" row at the tool layer), but the LiveCoding/UHT/UBT rows were not re-executed.

**Versioned-retest rule (answers "how long do `[ABS]` claims stay valid?"):** `[ABS]` is valid only
for the exact engine build + live `AllToolsets` set it was captured on. Store one baseline per major
(`ue583_baseline.json`, `ue59_baseline.json`); at each upgrade run the §7 diff, then re-search
**domain tokens** (not just names). Treat an `[ABS]` older than one engine minor as `[STALE]` until
re-diffed. The 5.8 verdicts above are historical evidence, not current truth on 5.9 — keep the
version in every tag.

### 6.5 §4 cross-cutting laws — law-by-law re-run on 5.9 (2026-11-23) `[VERIFIED 2026-11-23 UE5.9.0-EN]`

§6.4 deferred these; this pass runs each §4 law individually via `ToolsetRegistry.execute_tool`
on UE 5.9.0 commandlet (`CCC59Probe.uproject`). Evidence files:
`CCC/Saved/Logs/_ue59_sec4_probe{,2,3,4,5}.py` + matching `_ue59_sec4_probe*.txt`.

| Law (5.8) | 5.9 re-run result | Status |
|---|---|---|
| **§4.2** enum-array schema-lie: `collision_channels` string[] fails, numeric enum idx works, error doesn't name the param | **STRUCTURE GONE.** 5.9 `LevelToolset.FindActors` takes a single `filter:object` (`ActorSearchFilter`); `GetCollisionChannels` returns `["ObjectTypeQuery1".."ObjectTypeQuery6"]`. Both `filter.collisionChannels:["WorldStatic"]` and `[0]` were **accepted** (no conversion failure). Unknown key `collisionChannel` gives a precise "no such field on ActorSearchFilter: 'Filter.collisionChannel'" + full example struct. | **OBSOLETE on 5.9** — the trap was a 5.8 arg-schema artifact, redesigned away |
| **§4.3** modal blocker: AnimBP create hangs MCP (skeleton-picker) `[BLOCK]` | **No hang in commandlet.** `BlueprintToolset.Create` with `assetType=/Script/Engine.AnimBlueprint` returned in **0.08s** with `ERROR=Could not create Blueprint AnimBP_Probe` (no skeleton → clean failure, no modal, server alive). | **CHANGED** in 5.9 commandlet path; GUI-modal behaviour still untested — do not claim `[BLOCK]` cleared for the live editor |
| **§4.4** declared import gates (columns/header/interp_mode/cache) `[DOC]` | **CONFIRMED, more explicit.** `CurveTableToolset.ImportFile` rejected `RCIM_BOGUS` with *"Valid values: 0=RCIM_Linear, 1=RCIM_Constant, 2=RCIM_Cubic"* (enum values now named in the error — 5.8 note said the error was opaque). `DataTableToolset.ImportFile` validated schema object type; `StringTableToolset` source-file check; `DataRegistryTools.GetItems` → "Registry '__NONE__' not found. Available: (none)". Descriptions still state the column/header rules. | **HOLDS** + error quality improved `[VERIFIED ...]` |
| **§4.5** serialization (DiscoverTests first; one level instance at a time) `[DOC]` | **PARTLY RELAXED.** `ListTests()` with NO prior `DiscoverTests` returned `OK {"tests":[],"total":0}` — no ordering gate enforced on the read path (5.8 said DiscoverTests MUST run first). `EditLevelInstance` description still warns "only one level instance in edit mode at a time" (not executed — no level-instance asset). PCG `GetNodeDataView`/`ExecuteGraphInstance` still carry the "one actor at a time" note in description. | **DiscoverTests gate relaxed** `[VERIFIED ...]`; level-instance/PCG serialization still `[DOC]` |
| **§4.6** recompile gates (set_parent/retarget → recompile; CDO stale until compiled) `[DOC]` | **Tool calls confirmed; stale-read claim NOT proven either way.** On real BP `BP_Inventory`: `GetDefaultObject`→`Default__BP_Inventory_C`, `GetParent`→`/Script/Engine.Actor`, `CompileBlueprint`→OK, `SetParent`→OK in-memory. Descriptions still state "Blueprint must be recompiled afterward". Did NOT construct the set_parent→read-CDO-without-compile sequence needed to observe staleness. | **Partial** — calls `[VERIFIED ...]`; stale-CDO behaviour stays `[DOC]`/`[UNV]` |
| **§4.7** PIE-conditional (FocusOnActors refuses during PIE; cue needs PIE) `[DOC]` | **HARNESS LIMIT.** commandlet has no real PIE world: `StartPIE`→OK but `IsPIERunning`→`false`, `FocusOnActors([])`→OK. `ExecuteCueOnSelectedActor` reached param validation (requires `location`/`normal`). Cannot verify the PIE refusal in commandlet; needs a focused GUI editor. | **UNVERIFIED this pass** — do not upgrade |
| **§4.8** event-dispatcher output params not supported `[DOC]` | **CONFIRMED LIVE + new crash finding.** On a real dispatcher: `AddFunctionParam(bInputParam=False)` and `AddObjectFunctionParam(bInputParam=False)` both → `ERROR=Event dispatcher "ProbeDispatcher" only supports input parameters.`; input param → OK. **Separately:** calling `AddFunctionParam(bInputParam=False)` on a plain **EventGraph** crashed the editor: `Assertion failed: EntryNodes.Num() == 1 [BlueprintEditorUtils.cpp:5605]` (exit 3). | **HOLDS** (+ new `[VERIFIED ...]` crash hazard: never add output params to an EventGraph via this tool on 5.9) |

**Meta-verdict:** 3 laws materially changed (§4.2 trap gone, §4.3 no hang in commandlet, §4.5
DiscoverTests gate relaxed), 2 confirmed (§4.4, §4.8), 1 partially confirmed (§4.6), 1 blocked by
harness (§4.7 needs GUI PIE). This reinforces §6.4's versioned-retest rule: even *behavioural*
laws (not just tool presence) expire across engine versions — re-run them, don't inherit the tag.

## 7. How to re-verify (after any engine/plugin change)

```powershell
cd <skill>/scripts
python snapshot_toolsets.py --diff ../references/ue583_baseline.json   # toolset/tool delta
powershell -File refresh_schemas.ps1 -Live                            # recorded-param drift
```
Then re-run the Axis B representative probes. Patch upgrades have so far been tool-layer-safe
(0/144 broken references on 5.8.3) but **did** add params (`find_actors` gained three, one of which
carries the §4.2 trap) — always diff before trusting a cached signature.
