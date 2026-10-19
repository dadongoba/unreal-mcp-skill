# Independent editor instances

Runtime version: 3.17.0. Python 3.10+; standard library only. Windows identity
inspection uses PowerShell/Get-NetTCPConnection/CIM; macOS/Linux use lsof and ps.
Install lsof on Linux if it is absent. An unverifiable identity blocks managed writes.

## Register each project once

Use real .uproject and engine paths:

    python scripts/ue_connect.py register --instance scene-a --project <PROJECT_A.uproject> --engine <UE_ROOT> --port 8011
    python scripts/ue_connect.py register --instance scene-b --project <PROJECT_B.uproject> --engine <UE_ROOT> --port 8012
    python scripts/ue_connect.py list

State lives outside the skill in ~/.unreal-mcp/runtime.sqlite. --state-dir or
UNREAL_MCP_HOME selects a different state root. All cooperating clients must use
the same root to share locks. The old ~/.codely-cli/ue_connect_state.json is not
overwritten or silently trusted; re-register its intended project.

Legacy launch --project remains available for a single unambiguous registration.
When several instances exist, --instance is required for selection. --url can
select an explicit endpoint, but cannot override a contradictory instance.
Only local HTTP endpoints are supported in this release; remote authentication
and network identity are outside this runtime's isolation guarantee.

## Start or attach

    python scripts/ue_connect.py launch --instance scene-a
    python scripts/ue_connect.py launch --instance scene-b
    python scripts/ue_connect.py wait --instance scene-a --timeout 1200
    python scripts/ue_connect.py check --instance scene-b

launch returns code 3 after spawning; run wait in a separate shell call. Another
project's editor does not prevent launching the selected instance. The same
project already loading does prevent a second launch. Port occupancy is never
resolved by killing a process or selecting another endpoint.

The launcher passes -ModelContextProtocolStartServer and
-ModelContextProtocolPort=<registered-port>. To attach an already-open editor,
run ModelContextProtocol.StartServer <port> in THAT editor's console. Starting
another port in the same process stops its previous MCP server; use separate
editor processes for independent environments.

Plugin audit requires ModelContextProtocol, ToolsetRegistry, EditorToolset,
PythonScriptPlugin and AllToolsets. --fix-plugins on launch is an explicit request
to edit the selected .uproject, with a uniquely named backup. It is never enabled
implicitly. No universal first-load duration is assumed; check advancing logs
before deciding that a timeout indicates failure.

## Own a write task

    python scripts/ue_connect.py begin --instance scene-a --task-id scene-task-1
    python scripts/mcp_call.py --instance scene-a --task-id scene-task-1 --tool <TOOL> --toolset <TOOLSET> --args-file <ARGS.json>
    python scripts/ue_connect.py end --task-id scene-task-1

begin pins the endpoint, normalized project, listener PID and process start time.
It reserves both the instance and the project. Idle ownership expires after
900 seconds by default; each managed call renews the lease for 900 seconds.
Use a new task ID after expiry, completion or editor restart.

Another task cannot acquire either reserved resource. Simultaneous calls sharing
a task ID are also serialized by crash-released OS file locks; a busy call returns
an actionable error. Calls are not internally retried. Complete the whole
create/wire/compile/readback sequence under the same task.

Only list_toolsets and describe_toolset are classified as unowned discovery.
All other tool names conservatively require ownership, including queries with
unknown side effects. This is a deliberate behavior change from v3.16.

The PowerShell mcp_call.ps1 wrapper accepts -Instance, -TaskId, -McpUrl,
-ArgumentsFile, -ArgumentsJson, -ScriptPath and -ResultFile. It delegates to
Python instead of reusing a script-global MCP session across endpoints.

    python scripts/snapshot_toolsets.py --instance scene-a --out <LOCAL_SNAPSHOT.json>
    python scripts/refresh_schemas.py --live --instance scene-a

Python discovery scripts share the transport and target resolver. The older
refresh_schemas.ps1 remains a read-only schema diagnostic with explicit -McpUrl;
it does not provide task ownership. Prefer its Python twin for instance selection.

## Failures and limits

- HTTP 200 is not enough: JSON-RPC errors and tool isError also fail.
- The transport handles JSON and SSE and sends the negotiated protocol header.
- Sessions are initialized independently and closed on normal exit.
- A changed listener/process is rejected before a managed write.
- An expired/404 session does not cause automatic replay. Reconnect explicitly;
  read back first if the previous request might have changed UE.
- mcp_call exit 4 means a transport failure during a potentially mutating call;
  the result is unknown, not a confirmed failure.
- Locks coordinate this runtime's clients only. Native MCP tools, manually issued
  HTTP calls and UI editing do not participate.
- Separate ports do not isolate shared assets, RAM, GPU memory or input focus.
  Use separate project checkouts for parallel asset writes and serialize global
  keyboard/mouse automation. No running editor is stopped by this runtime.

Automated tests use independent simulated HTTP/SSE servers and local lock/state
checks. They do not certify simultaneous operation of real UE editors on every
platform. The port launch parameters are confirmed in UE 5.8.3 source.
