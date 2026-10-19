#!/usr/bin/env python3
"""Host-neutral task completion callback with a recoverable local journal.

The child receives UNREAL_MCP_TASK_ID and UNREAL_MCP_RECORD_FILE. It should write
an allowlisted, generic experience JSON there, never raw logs or project files.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

from ue_mcp.instances import InstanceError, Store, process_identity, valid_id


def finish(store, row):
    task_id, path, instance = row["task"], Path(row["record_path"]), row["instance"]
    try:
        if not path.is_file():
            with store.db:
                store.db.execute("UPDATE runner_tasks SET status='awaiting_record' WHERE task=?", (task_id,))
            print("No structured experience yet; local completion journal retained: " + task_id)
            return False
        command = [sys.executable, "-X", "utf8", str(Path(__file__).with_name("experience.py")),
                   "finalize", "--task-id", task_id, "--record-file", str(path),
                   "--state-dir", str(store.root)]
        if instance:
            command += ["--instance", instance]
        result = subprocess.run(command, check=False)
        with store.db:
            store.db.execute("UPDATE runner_tasks SET status=? WHERE task=?",
                             ("done" if result.returncode == 0 else "needs_review", task_id))
        return result.returncode == 0
    finally:
        store.end(task_id)


def prepare(store):
    store.db.execute("""CREATE TABLE IF NOT EXISTS runner_tasks(
        task TEXT PRIMARY KEY, record_path TEXT NOT NULL, instance TEXT,
        status TEXT NOT NULL, outcome INTEGER)""")
    store.db.commit()


def recover(store):
    rows = list(store.db.execute("SELECT * FROM runner_tasks WHERE status!='done'"))
    for row in rows:
        try:
            with store.file_lock("runner:" + row["task"]):
                finish(store, row)
        except InstanceError:
            continue  # A live wrapper still owns this task.


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--state-dir")
    ap.add_argument("--instance")
    ap.add_argument("--task-id", default=None)
    ap.add_argument("--record-file")
    ap.add_argument("--recover", action="store_true")
    ap.add_argument("command", nargs=argparse.REMAINDER)
    args = ap.parse_args()
    store = Store(args.state_dir)
    prepare(store)
    try:
        recover(store)
        if args.recover:
            return 0
        command = args.command[1:] if args.command[:1] == ["--"] else args.command
        if not command:
            ap.error("Supply a task command after --, or use --recover")
        task_id = valid_id(args.task_id or str(uuid.uuid4()))
        folder = store.root / "runs" / task_id
        folder.mkdir(parents=True, exist_ok=True)
        path = Path(args.record_file).resolve() if args.record_file else (folder / "experience.json").resolve()
        with store.file_lock("runner:" + task_id):
            if store.db.execute("SELECT 1 FROM runner_tasks WHERE task=?", (task_id,)).fetchone():
                raise InstanceError("Runner task ID already exists; use a new task ID")
            if args.instance:
                profile = store.resolve(args.instance)
                store.begin(profile, task_id, process_identity(profile["url"], profile["project"]))
            with store.db:
                store.db.execute("INSERT INTO runner_tasks VALUES(?,?,?,'running',NULL)",
                                 (task_id, str(path), args.instance))
            env = dict(os.environ, UNREAL_MCP_TASK_ID=task_id, UNREAL_MCP_RECORD_FILE=str(path),
                       UNREAL_MCP_INSTANCE=args.instance or "")
            outcome = 130
            try:
                outcome = subprocess.run(command, env=env, check=False).returncode
                return outcome
            finally:
                with store.db:
                    store.db.execute("UPDATE runner_tasks SET status='pending',outcome=? WHERE task=?",
                                     (outcome, task_id))
                row = store.db.execute("SELECT * FROM runner_tasks WHERE task=?", (task_id,)).fetchone()
                try:
                    finish(store, row)
                except (OSError, ValueError, InstanceError):
                    print("Completion journal retained for recovery: " + task_id, file=sys.stderr)
    except (OSError, ValueError, InstanceError) as error:
        print(str(error), file=sys.stderr)
        return 2
    finally:
        store.close()


if __name__ == "__main__":
    sys.exit(main())
