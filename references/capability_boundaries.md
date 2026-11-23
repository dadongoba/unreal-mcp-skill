# Capability Boundaries — UE 5.8.3 MCP (three-axis map)

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

## 7. How to re-verify (after any engine/plugin change)

```powershell
cd <skill>/scripts
python snapshot_toolsets.py --diff ../references/ue583_baseline.json   # toolset/tool delta
powershell -File refresh_schemas.ps1 -Live                            # recorded-param drift
```
Then re-run the Axis B representative probes. Patch upgrades have so far been tool-layer-safe
(0/144 broken references on 5.8.3) but **did** add params (`find_actors` gained three, one of which
carries the §4.2 trap) — always diff before trusting a cached signature.
