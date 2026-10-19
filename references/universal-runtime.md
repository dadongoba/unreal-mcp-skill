# Universal runtime, contract v1

The core is maintained once and deployed per user. MCP clients may use separate
server processes, all sharing the same local state and immutable package. Users
do not share editor sessions, credentials or project assets through this service.

Standards: [Agent Skills](https://agentskills.io/specification) for the skill
package and [MCP](https://modelcontextprotocol.io/specification/2025-11-25) for
tools. The UE lifecycle and package/experience formats below are this project's
versioned contracts, not additional official MCP standards.

## Install once, connect several clients

Python 3.10+; standard library only. From a trusted checkout:

~~~text
python scripts/unreal_mcp.py install --source .
python scripts/unreal_mcp.py adapter --skill-dir <CLIENT_SKILLS_DIRECTORY>/unreal-mcp
python scripts/unreal_mcp.py config
python scripts/unreal_mcp.py doctor
python scripts/unreal_mcp.py contract
~~~

Repeat adapter only for clients that load Skills. Existing directories are moved
to unique `~/.unreal-mcp/backups/adapters` folders outside skill discovery before
creating the small adapter. Local
customizations remain in those backups; they are not silently promoted into
shared instructions. Both adapters point to `~/.unreal-mcp/launch.py` and contain
no copied core scripts. `UNREAL_MCP_HOME` or the management CLI's `--home` selects
a different shared home. Use one home per local user/security boundary.

`config` emits an `mcpServers` JSON fragment using the actual Python executable
and absolute launcher path. Merge it using the client's documented MCP settings;
configuration syntax varies. The installer does not overwrite an application's
unrelated configuration. Equivalent generic stdio setup:

~~~json
{"command":"<PYTHON_EXECUTABLE>","args":["<SHARED_HOME>/launch.py","serve"],"env":{"UNREAL_MCP_HOME":"<SHARED_HOME>"}}
~~~

Start directly from a checkout when developing:

~~~text
python scripts/mcp_server.py --transport stdio --state-dir <STATE_DIRECTORY>
~~~

Do not point both the native UE server and this bridge at the same listener port.
The bridge connects to the registered UE MCP endpoints. Register/launch/wait with
`scripts/ue_connect.py` as documented in [multi-instance.md](multi-instance.md).
In an installed package, CLI `knowledge read SKILL.md` returns `package_root`;
resolve relative helper-script paths against that root.

## Capability-based compatibility

| Host capability | Entry point | Completion |
|---|---|---|
| Skills + MCP | Small adapter + MCP tools | ue_finish_task or verified host callback |
| MCP tools only | Read guidance with ue_knowledge_read | ue_finish_task |
| Local command execution | Shared CLI and existing Python helpers | explicit finalize or task_run.py |
| Remote MCP/HTTP tools | Authorized network bridge to the user's runtime | same task tools |
| Text only | Explain or generate manual instructions | cannot operate a local editor |

Protocol tests exercise 2024-11-05, 2025-03-26, 2025-06-18 and 2025-11-25.
This is protocol coverage, not certification of every commercial AI client.
The host retains its own execution permissions. MCP does not supply a universal
host task-completion event or expose the whole conversation to this service.

## Shared tool contract

1. ue_knowledge_read(path=SKILL.md), then load relevant domain guidance.
2. ue_status; select the intended instance. ue_register_instance can register an
   existing local project with an explicit local URL. It does not launch UE.
   ue_status also returns the shared automatic release check; ue_check_update
   supports force/offline checks. See [update discovery](update-discovery.md).
   Choose backend at registration and inspect ue_capabilities before first use;
   see [backends](backends.md) for live schema and actual validation limits.
3. ue_begin_task(instance) verifies process identity and returns a fresh task_id.
4. ue_call(instance, task_id, tool, toolset, arguments) discovers/executes UE tools
   using the same guarded runtime as mcp_call.py. `list_toolsets` and
   `describe_toolset` are the only task-free discovery calls. All other calls
   conservatively require ownership, including UE readback tools.
5. Verify compilation, readback or PIE behavior as appropriate.
6. ue_finish_task(task_id, record?) releases locks. Omit record when there is no
   useful lesson. Optional records follow schemas/experience.v1.json; use
   ue_knowledge_read to retrieve it. Invalid records release ownership and return
   an error; correct the generic record and retry finalization in the same session.

Task IDs cannot be used or finished by a different MCP session. Session closure
releases ownership; a crash leaves time-limited leases. Unknown write outcomes
must be reconciled by readback, never blindly replayed. A lost session cannot be
recovered by moving its task ID to a new session.

ue_experience_status reports saved consent and queue counts. Only the local user
configuration command enables public uploading; connecting an AI never enables
it. Configure it through `scripts/experience.py` in the installed package root.
See [experience-contribution.md](experience-contribution.md).

## Local HTTP and remote Work environments

~~~text
python scripts/unreal_mcp.py token
python scripts/mcp_server.py --transport http --port 8765 --token-file <SHARED_HOME>/http-token
~~~

Endpoint: `http://127.0.0.1:8765/mcp`. Every request requires
`Authorization: Bearer <TOKEN>`; the token is created privately and never printed
by setup. Protect its file with the local user's filesystem permissions.
HTTP rejects unexpected Host/Origin, has request/session bounds and offers
JSON responses; GET event streams are intentionally unsupported (405).

The HTTP listener accepts only loopback binding. A remote host needs an authorized
tunnel or a separately deployed HTTPS gateway with host-compatible authentication,
scoped credentials and access control. A cloud host's localhost is not the user's
computer. No public gateway, OAuth provider or cloud service is deployed by this
package. Host-controlled header injection or the client's authenticated connector
is required; a client that cannot provide either needs a dedicated adapter.
Never expose the raw UE port or token through a public unauthenticated tunnel.

## Releases, checks and rollback

~~~text
python scripts/unreal_mcp.py build --output dist/unreal-mcp-3.19.0.zip
python scripts/unreal_mcp.py install --archive <ZIP> --sha256 <TRUSTED_SHA256>
python <SHARED_HOME>/launch.py check
python <SHARED_HOME>/launch.py update
python <SHARED_HOME>/launch.py rollback
~~~

Install verifies the archive digest, bounded safe ZIP paths, complete per-file
manifest and runtime version. Packages are immutable versioned directories.
Activation changes one pointer; every adapter follows it on its next launch.
An active UE task blocks activation; begin-task and activation share an OS lock.
Reconnect idle MCP clients after upgrading: already-running processes stay on
their original package. Rollback selects the previous verified package; local
runtime state and preferences are retained. Database migrations must remain
backward-compatible for rollback to work.

`check`/`update` use stable releases from dadongoba/unreal-mcp-skill only. `update`
does not downgrade a newer local installation. No recurring update job is installed.
ue_status performs a cached automatic check when a host invokes it; this is not
a background job. Network failures remain unknown and do not block UE execution.
Before the first portable release is published, install from a trusted checkout
or reviewed archive. A checksum detects corruption; release trust comes from the
original repository and its reviewed maintainers.

Maintainers publish by pushing a version tag matching the runtime version. The
release workflow runs regressions and emits a ZIP plus release.json tied to its
source commit. Each version is published once. Do not tag unreproduced knowledge
as verified or retag a published version.

## Experience to published knowledge

Inbox reports are excluded from runtime knowledge searches. Prepare a candidate:

~~~text
python scripts/curate_experience.py propose --record contributions/inbox/<UUID>.json --output <CANDIDATE.json>
~~~

Reproduce in a controlled UE project, then supply a generic evidence JSON with
exactly these fields (the values below illustrate shape, not actual test evidence):

~~~json
{"reviewer":"MAINTAINER_LOGIN","checked_at":"2026-10-19","ue_version":"5.8.3","editor_language":"en","method":"pie_assertion","assertion":"Describe the observed generic runtime assertion.","passed":true,"maintainer_reproduced":true,"source_issue":"https://github.com/dadongoba/unreal-mcp-skill/issues/123"}
~~~

~~~text
python scripts/curate_experience.py promote --candidate <CANDIDATE.json> --evidence <EVIDENCE.json> --accept-reviewed --output knowledge/published/<UUID>.json
~~~

Promotion checks format, unchanged candidate content, sensitive patterns and
passing reproduction evidence. It cannot independently prove a maintainer ran
UE; review the evidence and resulting PR. CI rejects malformed published entries.
After review/merge/release, every updated runtime can retrieve the new knowledge.
Actual authoring changes still require a relevant regression test or UE assertion.
Submitted snippets never execute in intake, curation or release jobs.
