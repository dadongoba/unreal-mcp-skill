#!/usr/bin/env python3
"""Prepare an experience candidate, then promote only with explicit review evidence.

This does not execute submitted code or assert that a real UE test ran. A
maintainer supplies evidence after reproducing, and reviews the resulting diff.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

from ue_mcp.experience import public_check
from ue_mcp.packages import atomic_json


def propose(record):
    public_check(record)
    return {"format": 1, "status": "candidate", "record": record,
            "record_sha256": hashlib.sha256(json.dumps(record, sort_keys=True,
                                                        ensure_ascii=False).encode()).hexdigest()}


def promote(candidate, evidence):
    if candidate.get("status") != "candidate" or propose(candidate["record"]) != candidate:
        raise ValueError("Candidate changed or is invalid; regenerate and review it")
    required = {"reviewer", "checked_at", "ue_version", "editor_language", "method",
                "assertion", "passed", "maintainer_reproduced", "source_issue"}
    if not isinstance(evidence, dict) or set(evidence) != required:
        raise ValueError("Evidence must have exactly the documented fields")
    if (evidence["passed"] is not True or evidence["maintainer_reproduced"] is not True
            or evidence["method"] not in {"compile", "readback", "pie_assertion"}
            or not isinstance(evidence["assertion"], str) or not 10 <= len(evidence["assertion"]) <= 1000
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", evidence["reviewer"])
            or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", evidence["checked_at"])
            or not re.fullmatch(r"\d+\.\d+(?:\.\d+)?", evidence["ue_version"])
            or not re.fullmatch(r"[A-Za-z-]{2,20}", evidence["editor_language"])
            or not re.fullmatch(r"https://github\.com/dadongoba/unreal-mcp-skill/issues/\d+", evidence["source_issue"])):
        raise ValueError("Passing maintainer reproduction and scoped evidence are required")
    # Check free-form evidence for the same disallowed sensitive patterns.
    from ue_mcp.experience import sanitize
    clean, flags = sanitize(evidence["assertion"])
    if flags or clean != evidence["assertion"]:
        raise ValueError("Evidence assertion contains sensitive patterns")
    return {"format": 1, "status": "published", "record_id": candidate["record"]["record_id"],
            "record": candidate["record"], "evidence": evidence,
            "provenance": "Maintainer-supplied reproduction evidence; review the PR before release."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="cmd", required=True)
    candidate = subs.add_parser("propose")
    candidate.add_argument("--record", required=True)
    candidate.add_argument("--output", required=True)
    publish = subs.add_parser("promote")
    publish.add_argument("--candidate", required=True)
    publish.add_argument("--evidence", required=True)
    publish.add_argument("--output", required=True)
    publish.add_argument("--accept-reviewed", action="store_true", required=True)
    args = parser.parse_args()
    try:
        load = lambda path: json.loads(Path(path).read_text(encoding="utf-8-sig"))
        value = propose(load(args.record)) if args.cmd == "propose" else promote(load(args.candidate), load(args.evidence))
        output = Path(args.output)
        if output.exists():
            raise ValueError("Output already exists; review revisions explicitly")
        output.parent.mkdir(parents=True, exist_ok=True)
        atomic_json(output, value)
        print(str(output))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
