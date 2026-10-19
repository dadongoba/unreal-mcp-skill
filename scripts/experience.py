#!/usr/bin/env python3
"""Finalize local experience; explicitly opt in to publishing to the original repository."""
import argparse
import getpass
import json
from pathlib import Path
import sys

from ue_mcp.experience import ExperienceError, Queue
from ue_mcp.instances import InstanceError, Store


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--state-dir")
    sub = ap.add_subparsers(dest="cmd", required=True)
    config = sub.add_parser("configure", parents=[common])
    config.add_argument("--mode", choices=["off", "local", "auto"], required=True)
    config.add_argument("--accept-public-upload", action="store_true")
    config.add_argument("--deny-project")
    finalize = sub.add_parser("finalize", parents=[common])
    finalize.add_argument("--task-id", required=True)
    finalize.add_argument("--record-file", required=True)
    finalize.add_argument("--instance", help="bind privacy policy to the registered project")
    finalize.add_argument("--redact-file", help="local JSON array of additional private words")
    sub.add_parser("status", parents=[common])
    preview = sub.add_parser("preview", parents=[common])
    preview.add_argument("--record-id", required=True)
    publish = sub.add_parser("publish", parents=[common])
    publish.add_argument("--record-id", help="omit to attempt at most 10 eligible queued records")
    args = ap.parse_args()
    store = Store(args.state_dir)
    queue = Queue(store)
    try:
        if args.cmd == "configure":
            queue.configure(args.mode, args.accept_public_upload, args.deny_project)
            print(json.dumps(queue.config(), indent=2))
        elif args.cmd == "status":
            print(json.dumps({"config": queue.config(), "records": [
                dict(row) for row in store.db.execute(
                    "SELECT id,status,issue_url,attempts,error FROM contributions ORDER BY rowid DESC LIMIT 50")
            ]}, indent=2))
        elif args.cmd == "preview":
            row = store.db.execute("SELECT payload,status,error FROM contributions WHERE id=?",
                                   (args.record_id,)).fetchone()
            if not row:
                raise ExperienceError("Unknown experience ID")
            print(json.dumps({"status": row["status"], "flags": row["error"],
                              "record": json.loads(row["payload"])}, ensure_ascii=False, indent=2))
        elif args.cmd == "finalize":
            task = store.db.execute("SELECT instance FROM tasks WHERE id=?", (args.task_id,)).fetchone()
            if task and args.instance and task["instance"] != args.instance:
                raise ExperienceError("Privacy instance disagrees with the task binding")
            selected = args.instance or (task["instance"] if task else None)
            profile = store.resolve(selected) if selected or store.profiles() else None
            terms = [str(Path.home()), getpass.getuser()]
            for registered in store.profiles().values():
                terms += [registered["project"], Path(registered["project"]).stem]
                if registered.get("engine"):
                    terms.append(registered["engine"])
            if args.redact_file:
                extra = json.loads(Path(args.redact_file).read_text(encoding="utf-8-sig"))
                if not isinstance(extra, list) or not all(isinstance(item, str) for item in extra):
                    raise ExperienceError("--redact-file must be a JSON array of private words")
                terms += extra
            row = queue.finalize(args.task_id, json.loads(Path(args.record_file).read_text(encoding="utf-8-sig")),
                                 terms, profile["project"] if profile else None)
            if queue.config()["mode"] == "auto" and row["status"] == "queued":
                row = queue.publish(row["id"])
            print(json.dumps({key: value for key, value in row.items()
                              if key not in {"payload", "source_project"}}, indent=2))
        elif args.cmd == "publish":
            ids = ([args.record_id] if args.record_id else [
                row[0] for row in store.db.execute(
                    "SELECT id FROM contributions WHERE status IN ('queued','retry_wait','unknown','submitting') "
                    "ORDER BY rowid LIMIT 10")])
            for record_id in ids:
                result = queue.publish(record_id)
                print(json.dumps({key: value for key, value in result.items() if key != "payload"}))
        return 0
    except (ExperienceError, InstanceError, OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2
    finally:
        if args.cmd == "finalize":
            store.end(args.task_id)
        store.close()


if __name__ == "__main__":
    sys.exit(main())
