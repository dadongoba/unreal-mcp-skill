# UE Native CLI — offline batch channel (the third access layer)

> **Purpose.** Covers what neither MCP nor the shared runtime's knowledge tools can do:
> **headless batch work** — compile every Blueprint, validate all assets, cook, run Python
> without an attached editor. This is a third, complementary layer, not a replacement for MCP.
>
> Evidence: [DOC] = Epic official docs (5.6/5.8). `[VERIFIED 2026-11-21 UE5.8.4-EN]`
> = executed live on the CCC test bed (`F:\desktop\我开发的软件\TTT\CCC\CCC.uproject`,
> engine `5.8.4-58902052+++UE5+Release-5.8`, embedded Python 3.11.8). Four channels were
> run end-to-end: `CompileAllBlueprints`, `DataValidation`, `-run=pythonscript`,
> `-ExecutePythonScript`. Three undocumented gotchas found — see §2, §3, §4.
> Untested here: `cook`, `ResavePackages`, `LODRecipeCommandlet` (remain `[DOC]` / `[UNV]`).

## 0. Three layers, do not confuse them

| Layer | Entry | Link | State | Best at |
|---|---|---|---|---|
| ① Knowledge | `launch.py knowledge read` | plain files | offline, no editor | reading rules/docs |
| ② Live editor | MCP `ue_*` tools | plugin bridge, port 8000 | attached to a running editor | authoring/verifying graphs, scenes, assets |
| ③ **Batch CLI** | `UnrealEditor-Cmd.exe` | process | **headless, starts and exits** | bulk validate/compile/cook/script |

`§1.4` of `capability_boundaries.md` documents two *live* out-of-band channels
(`CmdLinkServer`, Python remote execution). Those attach to an open editor. This document is
the **offline** counterpart: a separate process that starts, does one job and quits.
The three layers do not compete — a batch CLI run does not occupy an editor instance.

**Routing rule:** change something → MCP (②). Read rules → knowledge (①).
Run a job over many assets → native CLI (③).

## 1. Locate the executable

```text
<UE_ROOT>\Engine\Binaries\Win64\UnrealEditor-Cmd.exe     # UE5
<UE_ROOT>\Engine\Binaries\Win64\UE4Editor-Cmd.exe        # UE4
```

Common install root: `C:\Program Files\Epic Games\UE_5.x`. Verify before use:

```bash
python -c "import glob;print('\n'.join(glob.glob(r'C:\Program Files\Epic Games\UE_*\Engine\Binaries\Win64\UnrealEditor-Cmd.exe')))"
```

Add the Win64 folder to `PATH` to call `UnrealEditor-Cmd.exe` directly, or use the full path.

## 2. Commandlets — one-shot jobs `[DOC]`

Shape: `UnrealEditor-Cmd.exe "<PROJECT.uproject>" -run=<Commandlet> [flags]`

| Commandlet | Use | Typical flags | Test result on CCC |
|---|---|---|---|
| `CompileAllBlueprints` | Recompile every Blueprint; catch errors after engine/C++ changes | `-ProjectOnly` | `[VERIFIED]` exit **12** with 24 errors / 4 warnings; **no assets written** |
| `DataValidation` | Validate assets against the project's validation rules (missing refs, bad values, naming) | — | `[VERIFIED]` exit **1**; also reports asset-load/compiler errors, not just naming |
| `ResavePackages` | Resave packages; also rebuilds lighting | `-BuildLighting -AllowCommandletRendering -MapsOnly -Quality=Preview` | `[UNV]` |
| `cook` | Cook platform content | `-targetplatform=WindowsNoEditor -Map=<Map> -iterate` | `[UNV]` |
| `LODRecipeCommandlet` | Build LOD recipes | `-Save -LODRecipes=<names> -AllowCommandletRendering` | `[UNV]` |

**Non-zero exit is the signal.** Both verified commandlets returned non-zero precisely when
they found the CCC test bed's deliberately broken Blueprints (`/Game/TestT1/BP_Inventory`,
`BP_Pickup` — bad casts, missing functions `UpdateCount`/`AddItem`). This matches the failure
forms catalogued in `capability_boundaries.md` and `history/case_testT1_inventory.md`:
the offline CLI reproduces MCP-era faults. Treat exit ≠ 0 as "found issues", not "tool broke".

**`-help` does NOT print help on `CompileAllBlueprints`.** `[VERIFIED 2026-11-21]` Passing
`-help` was silently ignored and the full compile ran anyway. Do not use `-help` as a dry-run.

`-AllowCommandletRendering` is required whenever a job needs rendering (lighting, material
baking for LOD) — without it the process may not run. `[DOC]`

**Why this layer matters:** `CompileAllBlueprints` and `DataValidation` are exactly the bulk
checks that MCP cannot expose and that are painful by hand across many assets. Prefer them for
CI / pre-flight gates.

## 3. Python from the command line `[VERIFIED 2026-11-21 UE5.8.4-EN]`

Requires the project to enable **Python Editor Script Plugin** and (for option A)
**Editor Scripting Utilities**. UE embeds **Python 3.11.8** — no separate install needed.
Both forms below ran successfully on the CCC test bed.

```bash
# A. Full editor: opens project, loads default map, then runs the script. Slower, sees the level.
#    [VERIFIED] took >5 min here; reported editor_world=/Temp/Untitled_1, 138 actors.
UnrealEditor-Cmd.exe "<PROJECT.uproject>" -ExecutePythonScript="C:\scripts\job.py"

# B. Commandlet: fastest (0.81 s), no UI, does NOT load a level. Add load_level yourself.
#    [VERIFIED] exit 0, "Python script executed successfully".
UnrealEditor-Cmd.exe "<PROJECT.uproject>" -run=pythonscript -script="C:\scripts\job.py"

# B-inline: pass statements directly; \n escapes newlines. [DOC — not run]
UnrealEditor-Cmd.exe "<PROJECT.uproject>" -run=pythonscript -script="a=5 \nb=10 \nprint(a+b)"
```

**Gotcha 1 — `print()` output does not reach the commandlet log.** `[VERIFIED 2026-11-21]`
A probe script's `print()` lines were absent from the redirected stdout even though the log
said `Python script executed successfully`. For any verification result, **write a file** from
inside the script (`open(path,"w").write(...)`) and read that file afterwards. Do not trust
console output as evidence.

**Gotcha 2 — option A is dramatically slower.** `[VERIFIED 2026-11-21]` The full-editor path
exceeded a 5-minute launch window on CCC; the commandlet path finished in under a second.
Prefer `-run=pythonscript` unless the script genuinely needs the loaded default map.

**Gotcha 3 — option B does not auto-load a level** `[DOC]`. Add at the top if needed:

```python
import unreal
unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).load_level("/Game/maps/MyMap.MyMap")
```

Scripts run once and the editor exits afterwards. Python is editor-only — not available in
PIE / Standalone / cooked builds.

Inside a Python job the full unsandboxed `unreal` module is available (unlike MCP's
`ProgrammaticToolset`, which is restricted to `re time copy math datetime json`). This is the
same escape hatch as §1.4 but driven offline. Confirmed present on CCC `[VERIFIED]`:
`unreal.LevelEditorSubsystem`, `unreal.EditorAssetLibrary`,
`unreal.SystemLibrary.get_engine_version()`.

## 4. Do not use `-ExecCmd=py ...` `[DOC]`

The official docs explicitly warn against launching with `ExecCmd` set to a `py` command: the
script can run before the editor environment is ready (default map not yet loaded). Use
`-ExecutePythonScript` or `-run=pythonscript` instead.

## 5. Safety and scope

- **`CompileAllBlueprints` does not write assets back.** `[VERIFIED 2026-11-21]` After a full
  compile on CCC (including 24 errors), all 361 `.uasset` mtimes were unchanged. It is a safe
  read-only diagnostic. Jobs with `-Save` or mutating Python still do write — back up first.
- Do not run a batch job against a project whose editor is open for interactive work —
  competing writers corrupt state. Confirm no live task/editor owns the project first.
- Commandlet flags are version-specific. Do **not** rely on `-help` as a dry run (§2 — it was
  ignored and the job executed). Check `<exe> -help` output only for commandlets known to
  honour it, and always capture the exit code and the full log.
- This runtime's task locks and identity checks cover MCP/CLI calls through `mcp_call.py`.
  A native `UnrealEditor-Cmd` process is outside those locks — serialize it manually.

## 6. Verification checklist for a batch run

1. Confirm the exact engine path and project path on this machine.
2. Confirm no editor instance currently owns the project (MCP `ue_status` / process list).
3. Run the commandlet / script; capture exit code AND full log to a file.
4. If using Python, have the script write results to a file — `print()` is not captured (§3).
5. Verify the result on disk (reopen the asset via MCP read tools or check the log report).
6. Record any new verified fact with a `[VERIFIED <date> UE<version>-<lang>]` tag.
