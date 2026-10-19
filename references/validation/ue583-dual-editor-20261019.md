# Live dual-editor validation — 2026-10-19

Environment: Windows, Unreal Engine 5.8.3 (CL 58210709), English tool/node
identifiers, v3.18 runtime, official MCP Python SDK 2.3.0. Two freshly created
projects ran as distinct UnrealEditor.exe processes on ports 18011 and 18012.
The editors used NullRHI/unattended mode; these were real engine processes,
not mocked MCP servers. Test state was separate from normal user registrations.

## Observed results

| Check | Observation |
|---|---|
| Shared stdio runtime | Two SDK clients launched the installed shared entrypoint and discovered each real editor's toolsets. |
| Process/project identity | Registering one project's path against the other editor's port was rejected before acquiring a write task. |
| Session ownership | A different MCP session could not use another session's task ID. |
| Instance ownership | A second task could not acquire an already-owned instance. |
| Real object isolation | Identically labelled TargetPoint actors read back X=101 in A and X=202 in B, including after operations on both editors. |
| Blueprint isolation | Same asset path in separate projects retained distinct BeginPlay string literals. Both graphs compiled with warnings treated as errors; DSL readback confirmed the intended literal and absence of the other project's literal. |
| Asset persistence | Both project Blueprint files existed on disk after explicit save (31,237 bytes each). |
| Actual runtime behavior | Starting PIE/Simulate in A produced A's Blueprint log marker while B remained stopped; the inverse passed for B. Both PIE sessions were stopped after verification. |
| UE session expiration | After deleting the actual UE session for A, further use of that session failed; the existing B session continued to return the same inventory. No automatic replay occurred. |
| Authenticated HTTP | Official SDK Streamable HTTP calls through the local authenticated bridge acquired a task and read the real current world. |
| Experience completion | A schema-valid generic record entered the local queue, with no Issue URL and zero publish attempts. Public uploading remained disabled. |
| Normal HTTP shutdown | A real task intentionally left owned by a disconnected HTTP client was closed immediately when the bridge server shut down; no active task remained in the test store. |

Raw tool responses, engine logs, project descriptors and generated assets stay
local. This report contains generic observations only. It does not establish
coverage for other engine versions, every AI product, rendering/GPU behavior,
or a hosted remote Work connection.

## Failures found and their handling

- A listening TCP port appeared before engine initialization finished. The first
  read-only MCP handshake timed out; discovery succeeded after initialization.
  The observed cold initialization was about 845 seconds, not a general startup
  guarantee. Do not treat an open socket as proof that UE tools are ready.
- Generic `AssetTools.duplicate` of the engine Entry world did not produce a
  safely saveable map: save returned false with an illegal private Model object
  reference to the source world. That attempt failed. Subsequent tests used the
  in-memory editor world and saved only project Blueprint assets. Map Save As
  and map persistence remain unverified by this run.
- The original tool-error handler hid UE's useful diagnostic text. It now keeps
  a bounded original message and retains the original result on ToolError.
- A short HTTP client's timeout interrupted verification, and normal bridge
  shutdown left an owned task leased. HTTP shutdown now closes its sessions and
  releases their tasks; a regression covers this path. Use an end-to-end client
  timeout long enough for process identity checks and the selected UE operation
  (180 seconds was used for the live HTTP test).
- Actual host discovery also exposed Skill backups as duplicate active skills.
  Adapter backups now live in the shared home's backup directory, outside the
  clients' skill discovery directories. Existing backup contents are preserved.

## Reproduction outline

1. Create two empty disposable UE projects with the required MCP/toolset plugins.
   Start separate editors on distinct ports; preserve all existing user editors.
2. Wait for successful MCP initialization, then register the exact project/port
   pairs in an isolated state directory.
3. Connect two standard MCP clients to the same shared runtime/state. Test both
   successful task acquisition and the identity/ownership rejection cases.
4. Create the same object/asset names with distinct values in each project.
   Read back both targets, compile and read back the Blueprint graphs, save only
   the intended project assets and inspect their disk files.
5. Run PIE in one editor at a time. Assert its own distinct Blueprint marker and
   that the other editor has not entered PIE. Stop PIE before editing graphs.
6. Exercise independent UE session deletion, authenticated HTTP readback and
   local-only experience finalization. End all tasks and release test resources.

The automated mock/SDK regressions complement these observations; they do not
replace real UE behavior checks or certify map saving and visual output.
