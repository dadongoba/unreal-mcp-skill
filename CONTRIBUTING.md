# Contributing

## Structured experience contributions

Experiences go directly to the original dadongoba/unreal-mcp-skill repository.
See [the contribution runtime](references/experience-contribution.md) for explicit
opt-in, local-only mode, privacy boundaries and task completion integration.
The owner installs the intake workflow on master and enables Actions PR creation.
Contributors do not need a fork or repository write access.

Raw submissions may be unresolved observations or reporter-verified cases.
The default-branch workflow validates JSON DATA and writes only a single inbox
record to a submission branch, then opens a draft PR. It never executes submitted
code or promotes the prose into skill instructions. Public Issue submission
happens after local redaction and is already public before review.

Reproduction and confidence tagging below apply when promoting an inbox record
to formal rules/templates. Individual incoming records do not bump the skill
version or modify the lawbook. Keep private project terms and actual assets out
of the payload; a generic minimum reproduction is more useful.

Use the v3.18 [candidate and promotion commands](references/universal-runtime.md#experience-to-published-knowledge)
to preserve reporter evidence separately from maintainer reproduction. CI checks
published JSON entries. Review and merge before tagging a portable runtime release;
updates make the same published knowledge available to every compatible client.

This skill grows from **verified failures**. The most valuable contribution is a
`[VERIFIED]` lesson from a real UE session.

## How lessons get in (Self-Maintenance Protocol)

1. During a session: accumulate draft notes (one line each) — do not edit skill files mid-task.
2. At milestones (session end / ≥5 lessons): batch-commit into the matching capability doc
   or references/core-workflows.md lawbook, update cross-references + release
   metadata, one backup + one repackage.
3. **Only commit after verification succeeds** — unverified guesses do not belong in the lawbook.

## Confidence tags (mandatory)

| Tag | Meaning |
|---|---|
| `[VERIFIED <date> UE<ver>-<lang>]` | PIE- or user-confirmed. Highest trust. |
| `[DOC]` | Transcribed from official docs/dictionary, not battle-tested. |
| `[UNVERIFIED]` | Theoretically sound, expect failures. Verify before relying. |

When practice contradicts a `[VERIFIED]` entry twice → mark it `[STALE]` and fix it.

## Where things belong

- A **new pitfall/law** → the matching `references/capabilities/<domain>.md` §4, or SKILL.md
  if cross-domain (G-sections, max 12KB budget for the pitfall area).
- A **verified DSL workflow** → `references/templates/<name>.txt` (standard template structure;
  update `templates/README.md` index).
- **Syntax rules** → `references/dsl_syntax.md` (R-numbers).
- **Environment/platform facts** → SKILL.md or `references/platform-macos.md`.

## Pull-request checklist

- [ ] New factual entries carry a confidence tag with date and UE version
- [ ] No machine-local paths (usernames, drive letters tied to a specific machine) —
      parameterize them
- [ ] No secrets/tokens (obviously — but scan anyway)
- [ ] `python3 scripts/refresh_schemas.py` reports **0 DRIFT** (offline cross-check
      between tool_schemas.md and capability docs)
- [ ] Python scripts are stdlib-only and ASCII-safe; PowerShell scripts are PS5.1-compatible
- [ ] Formal releases update SKILL.md version + CHANGELOG.md; inbox submissions do not

## Trademark note

Unreal Engine is a trademark of Epic Games, Inc. Describe engine facts; never imply
endorsement.
