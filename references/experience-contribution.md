# Task experience and original-repository intake

Destination is fixed: https://github.com/dadongoba/unreal-mcp-skill .
No fork or second experience repository is required.

## Privacy and consent

Default mode is local. Each user must explicitly choose public auto mode after
reviewing this policy and a preview. The repository owner's consent does not opt
in other users. Public Issues can be read before review or merge; GitHub account
identity may be visible.

Allowlisted records contain UE/skill version, language/platform, domain, generic
symptom, preconditions, failed attempts, cause if known, solution/case steps and
actual verification. No assets, .uproject contents, screenshots, transcripts,
complete logs, tool dumps, engine source or proprietary project code are collected.
Do not copy raw material and rely on redaction afterwards: derive a generic
summary first. The finalizer reads only the explicitly supplied JSON file.

The strict schema rejects unknown fields and bounds text, arrays and total size.
Known paths, asset identifiers, contacts, URLs and private words are replaced.
Detected credentials/control characters move the sanitized record to needs_review.
Pattern checks cannot prove that free-form business information is anonymous.
Keep uncertain records local and supply extra private terms with --redact-file.

    python scripts/experience.py configure --mode local
    python scripts/experience.py configure --mode auto --accept-public-upload
    python scripts/experience.py configure --mode auto --accept-public-upload --deny-project <PRIVATE.uproject>
    python scripts/experience.py configure --mode off

--accept-public-upload authorizes future safe queued submissions by this user to
the fixed PUBLIC original repository. It does not publish project files. off
stops new collection and all publishing; local stops remote publishing. Project
denials also apply to records queued before the denial was added. The existing
outbox remains local so it can be reviewed; no automatic deletion is performed.

GitHub CLI is an optional publishing dependency. Users authenticate through their
own gh auth login; no maintainer credential is distributed. Confirm secure
credential storage because gh may fall back to plaintext storage on some hosts.
Offline or unauthorized publishing retains the record and never changes UE assets.

## Build the record

Use schemas/experience.v1.json. The following is a format example, not a verified
engine claim; replace its prose with actual task evidence:

~~~json
{
  "kind": "unresolved",
  "environment": {
    "ue_version": "5.8.3",
    "editor_language": "en",
    "platform": "windows"
  },
  "domain": "blueprint",
  "symptom": "A generic component event did not fire.",
  "preconditions": ["Two primitive actors in an empty test map."],
  "attempts": [{"action": "Compile the Blueprint.", "result": "The event still did not fire."}],
  "cause": "",
  "solution": [],
  "verification": {
    "status": "observed",
    "method": "none",
    "assertion": "",
    "maintainer_reproduced": false
  },
  "generic_reproduction": ["Create the generic actors and check the event during PIE."]
}
~~~

schema_version, record_id (random UUID) and environment.skill_version are filled
in locally if absent. Closed task IDs are unrelated to public record IDs. Repeated
finalization with the same evidence is idempotent; identical sanitized knowledge
from another task is deduplicated. Changed evidence needs a new revision task ID.
Successful cases and unresolved observations are both acceptable. A reporter
cannot claim maintainer reproduction.

    python scripts/experience.py finalize --task-id <TASK_ID> --instance <INSTANCE> --record-file <GENERIC_RECORD.json>
    python scripts/experience.py status
    python scripts/experience.py preview --record-id <RECORD_UUID>
    python scripts/experience.py publish --record-id <RECORD_UUID>

An additional private-term file is a LOCAL JSON array of words/names, passed to
finalize with --redact-file. The finalized outbox stores sanitized JSON only;
the caller owns the original draft file and its retention.

In auto mode finalize attempts publication immediately. Without auto consent,
publish refuses. Before a remote create, the publisher reconciles by record ID.
A lost create response remains unknown; it searches again later without blindly
creating a duplicate. Five failures before a write stop automatic retries.
There is no hidden background uploader or retry loop; subsequent finalize/publish
events or the task wrapper drive progress.

## Reliable completion integration

The skill asks its host to call finalize at a real task boundary. For a command
based agent/runner, use the host-neutral completion wrapper:

    python scripts/task_run.py --instance <INSTANCE> --task-id <TASK_ID> -- <AGENT_COMMAND_AND_ARGS>

The child gets UNREAL_MCP_TASK_ID, UNREAL_MCP_INSTANCE and
UNREAL_MCP_RECORD_FILE. Instruct it to write a generic record to that final path.
The wrapper streams the command normally, preserves its exit code, calls finalize
on success or failure, and releases the task. It never uploads child stdout/stderr.
Local completion journals survive a wrapper crash:

    python scripts/task_run.py --recover

Recovery also runs at the start of the next wrapper invocation; live wrappers are
skipped using OS locks. No draft produces awaiting_record instead of fabricated
experience. Unsupported hosts must invoke finalize explicitly. This release does
not install or claim a universal Codex/Codely hook.

## Original-repository GitHub workflow

The client creates a structured Issue in dadongoba/unreal-mcp-skill. Once the
experience-intake workflow is on master, GitHub Actions reads its trusted default-
branch code, validates the event as DATA, and creates:

    original repository branch: submissions/experience-<RECORD_UUID>
    original repository file:   contributions/inbox/<RECORD_UUID>.json
    draft pull request:         submission branch -> master

The Issue title and envelope must match the validated UUID. The server fixes the
repository, base branch, path prefix and file type; clients cannot request Git
operations or arbitrary paths. No submitted code is executed. Repeated workflow
runs reuse matching files/PRs; changed content under the same ID is refused.

Owner activation after reviewing/merging this implementation:

1. Enable Actions for the repository.
2. In Settings > Actions > General > Workflow permissions, enable "Allow GitHub
   Actions to create and approve pull requests." The workflow never approves or
   merges a PR; this GitHub setting is required for its PR creation.
3. Keep default token permissions read-only. Only the intake job requests
   contents:write and pull-requests:write.
4. Authenticate each contributing user's gh and obtain that user's public-upload
   consent. No shared PAT, app private key or custom backend secret is needed.

Issues created before workflow activation remain in the original repository;
an edit after activation can trigger intake. Client status submitted means the
Issue exists, not that its data PR has already been created or merged.
PRs created with GITHUB_TOKEN may not trigger other PR workflows; schema/privacy
validation therefore runs inside intake before any write. Review/reproduction is
still needed before formal rules or scripts change.

For larger deployments, a GitHub App-backed receiver can replace the Issue entry
point while keeping this schema/outbox and original repository. That service and
its credentials are not deployed by this release.
