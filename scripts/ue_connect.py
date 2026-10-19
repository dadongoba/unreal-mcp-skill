#!/usr/bin/env python3
"""Register, inspect and launch independent UE MCP instances; begin/end write tasks."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.parse import urlsplit

from ue_mcp.instances import InstanceError, Store, process_identity, project_is_running
from ue_mcp.transport import Client, MCPError
from ue_mcp.backends import BACKENDS
from snapshot_toolsets import parse_toolsets

REQUIRED_PLUGINS = ["ModelContextProtocol", "ToolsetRegistry", "EditorToolset",
                    "PythonScriptPlugin", "AllToolsets"]


def audit_plugins(project):
    data = json.loads(Path(project).read_text(encoding="utf-8-sig"))
    enabled = {p.get("Name") for p in data.get("Plugins", []) if p.get("Enabled")}
    return [p for p in REQUIRED_PLUGINS if p not in enabled], data


def fix_plugins(project):
    missing, data = audit_plugins(project)
    if missing:
        path = Path(project)
        backup = path.with_name(path.name + "." + str(time.time_ns()) + ".bak")
        backup.write_bytes(path.read_bytes())
        data.setdefault("Plugins", []).extend({"Name": name, "Enabled": True} for name in missing)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return missing


def editor_binary(root):
    if not root:
        return None
    relative = ("Engine/Binaries/Win64/UnrealEditor.exe" if sys.platform == "win32"
                else "Engine/Binaries/Mac/UnrealEditor.app/Contents/MacOS/UnrealEditor"
                if sys.platform == "darwin" else "Engine/Binaries/Linux/UnrealEditor")
    path = Path(root) / relative
    return str(path) if path.is_file() else None


def listening(url):
    parts = urlsplit(url)
    try:
        with socket.create_connection((parts.hostname, parts.port), timeout=1):
            return True
    except OSError:
        return False


def check(profile):
    identity = None
    if profile.get("project"):
        identity = process_identity(profile["url"], profile["project"])
    with Client(profile["url"], timeout=15) as client:
        from ue_mcp.backends import discover
        capabilities = discover(client, profile.get("backend", "epic-toolsets"))
        toolsets = []
        if capabilities["backend"] == "epic-toolsets":
            result = client.call("list_toolsets")
            text = "\n".join(item.get("text", "") for item in result.get("content", []))
            toolsets, _ = parse_toolsets(text)
        if identity and process_identity(profile["url"], profile["project"]) != identity:
            raise InstanceError("Editor changed during discovery")
    print(json.dumps({"instance": profile.get("name"), "url": profile["url"],
                      "identity_verified": identity is not None,
                      "identity": identity, "toolsets": len(toolsets),
                      "capabilities": capabilities}, indent=2))
    return identity


def launch(store, profile, fix=False):
    if profile.get("backend", "epic-toolsets") != "epic-toolsets":
        raise InstanceError("Automatic launch/plugin edits are Epic-only; configure and start this backend using its own instructions")
    if not profile.get("project"):
        raise InstanceError("Register the project before launching an editor")
    # Locks protect launch from other managed launchers for this instance and project.
    with store.file_lock("launch:" + profile["url"]), store.file_lock("project:" + profile["project"]):
        if listening(profile["url"]):
            process_identity(profile["url"], profile["project"])
            print("The selected editor is already listening; run check")
            return 1
        # Reject a second process for the same project even while it is still loading.
        if project_is_running(profile["project"]):
            raise InstanceError("This project already has an editor process; run wait instead")
        binary = editor_binary(profile.get("engine"))
        if not binary:
            raise InstanceError("Register a valid --engine root for this instance")
        missing, _ = audit_plugins(profile["project"])
        if missing and not fix:
            raise InstanceError("Missing plugins: {}; use --fix-plugins if authorized".format(", ".join(missing)))
        if missing:
            fix_plugins(profile["project"])
        options = ({"creationflags": 0x00000008 | 0x00000200} if sys.platform == "win32"
                   else {"start_new_session": True})
        child = subprocess.Popen([binary, profile["project"], "-ModelContextProtocolStartServer",
                                  "-ModelContextProtocolPort={}".format(urlsplit(profile["url"]).port)],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, **options)
        print("Launched {} on {}; run wait in a separate shell call".format(child.pid, profile["url"]))
        return 3


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--state-dir")
    common.add_argument("--instance")
    common.add_argument("--url")
    sub = ap.add_subparsers(dest="cmd", required=True)
    register = sub.add_parser("register", parents=[common])
    register.add_argument("--project", required=True)
    register.add_argument("--engine")
    register.add_argument("--port", type=int)
    register.add_argument("--backend", choices=BACKENDS, default="epic-toolsets")
    sub.add_parser("list", parents=[common])
    for name in ("check", "launch", "wait", "all"):
        parser = sub.add_parser(name, parents=[common])
        parser.add_argument("--project", help="legacy single-instance registration")
        parser.add_argument("--engine")
        parser.add_argument("--port", type=int)
        parser.add_argument("--timeout", type=int, default=420)
        if name in ("launch", "all"):
            parser.add_argument("--fix-plugins", action="store_true")
    begin = sub.add_parser("begin", parents=[common])
    begin.add_argument("--task-id", required=True)
    begin.add_argument("--lease-seconds", type=int, default=900)
    end = sub.add_parser("end", parents=[common])
    end.add_argument("--task-id", required=True)
    args = ap.parse_args()
    store = Store(args.state_dir)
    try:
        if args.cmd == "list":
            print(json.dumps(store.profiles(), indent=2))
            return 0
        if args.cmd == "end":
            store.end(args.task_id)
            print("Task ended: " + args.task_id)
            return 0
        if getattr(args, "port", None) is not None and not 1 <= args.port <= 65535:
            raise InstanceError("Port must be between 1 and 65535")
        if getattr(args, "project", None):
            url = args.url or "http://127.0.0.1:{}/mcp".format(args.port or 8000)
            if args.url and args.port and urlsplit(args.url).port != args.port:
                raise InstanceError("--port disagrees with --url")
            # Preserve the old --project syntax only for an unambiguous single instance.
            if not args.instance and len(store.profiles()) > 1:
                raise InstanceError("Specify --instance when registering among multiple projects")
            name = args.instance or "default"
            profile = store.register(name, args.project, url, args.engine,
                                     getattr(args, "backend", "epic-toolsets"))
            if args.cmd == "register":
                print(json.dumps(profile, indent=2))
                return 0
        elif args.cmd == "register":
            raise InstanceError("Registration requires --project")
        else:
            profile = store.resolve(args.instance, args.url)
            if getattr(args, "port", None) and urlsplit(profile["url"]).port != args.port:
                raise InstanceError("Register the requested port explicitly before using it")
        if args.cmd == "begin":
            if not profile.get("name"):
                raise InstanceError("Register an instance before beginning a write task")
            identity = process_identity(profile["url"], profile["project"])
            store.begin(profile, args.task_id, identity, args.lease_seconds)
            print("Task bound: {} -> {}".format(args.task_id, profile["name"]))
            return 0
        if args.cmd == "launch":
            return launch(store, profile, args.fix_plugins)
        if args.cmd == "all" and not listening(profile["url"]):
            return launch(store, profile, args.fix_plugins)
        if args.cmd in ("check", "all"):
            check(profile)
            return 0
        if args.timeout < 1:
            raise InstanceError("Timeout must be positive")
        deadline, report_at = time.monotonic() + args.timeout, time.monotonic()
        while time.monotonic() < deadline:
            try:
                check(profile)
                return 0
            except (InstanceError, MCPError, OSError):
                if time.monotonic() >= report_at:
                    print("Waiting for selected endpoint {}; no other instance will be used".format(profile["url"]), flush=True)
                    report_at = time.monotonic() + 30
                time.sleep(min(5, max(0, deadline - time.monotonic())))
        raise InstanceError("Wait timed out; inspect the selected project's log before relaunching")
    except (InstanceError, MCPError, OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2
    finally:
        store.close()


if __name__ == "__main__":
    sys.exit(main())
