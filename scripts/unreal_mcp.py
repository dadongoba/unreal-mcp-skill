#!/usr/bin/env python3
"""Portable Unreal MCP setup, diagnostics, package activation and tools."""
import argparse
import json
import os
from pathlib import Path
import platform
import secrets
import shutil
import sys
import tempfile

from ue_mcp import VERSION, knowledge
from ue_mcp.experience import Queue
from ue_mcp.instances import Store
from ue_mcp.packages import Manager, ROOT, build, download, latest, verify
from ue_mcp.updates import check as check_update, local as local_version


def main():
    # Forward server arguments without reinterpreting them as management commands.
    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        import mcp_server
        sys.argv = [sys.argv[0], *sys.argv[2:]]
        return mcp_server.main()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", help="shared runtime/state directory (default UNREAL_MCP_HOME or ~/.unreal-mcp)")
    subs = parser.add_subparsers(dest="cmd", required=True)
    pack = subs.add_parser("build")
    pack.add_argument("--source", default=str(ROOT))
    pack.add_argument("--output", required=True)
    install = subs.add_parser("install")
    inputs = install.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--source")
    inputs.add_argument("--archive")
    install.add_argument("--sha256")
    install.add_argument("--skill-dir", action="append", default=[])
    check = subs.add_parser("check")
    check.add_argument("--force", action="store_true")
    check.add_argument("--offline", action="store_true")
    capabilities = subs.add_parser("capabilities")
    capabilities.add_argument("--instance", required=True)
    subs.add_parser("update")
    subs.add_parser("rollback")
    subs.add_parser("config")
    subs.add_parser("doctor")
    subs.add_parser("contract")
    subs.add_parser("token")
    adapter = subs.add_parser("adapter")
    adapter.add_argument("--skill-dir", required=True)
    know = subs.add_parser("knowledge")
    know.add_argument("operation", choices=("read", "search"))
    know.add_argument("value", nargs="?", default="SKILL.md")
    args = parser.parse_args()
    try:
        if args.cmd == "build":
            value = build(args.source, args.output)
        elif args.cmd == "contract":
            from ue_mcp.bridge import PROTOCOLS, TOOLS
            value = {"contract_version": 1, "runtime_version": VERSION,
                     "protocol_versions": PROTOCOLS, "tools": TOOLS}
        elif args.cmd == "knowledge":
            value = (knowledge.read(args.value) if args.operation == "read" else knowledge.search(args.value))
            value["package_root"] = str(ROOT)
        else:
            manager = Manager(args.home)
            if args.cmd == "install":
                with tempfile.TemporaryDirectory(prefix="ue-install-") as folder:
                    if args.source:
                        archive = Path(folder) / "package.zip"
                        metadata = build(args.source, archive)
                        checksum = metadata["sha256"]
                    else:
                        archive, checksum = Path(args.archive), args.sha256
                        if not checksum:
                            raise ValueError("--archive requires the trusted --sha256")
                    value = manager.install(archive, checksum)
                value["adapters"] = [manager.adapter(path) for path in args.skill_dir]
                value["config"] = manager.config()
            elif args.cmd == "rollback":
                value = manager.rollback()
            elif args.cmd == "adapter":
                value = manager.adapter(args.skill_dir)
            elif args.cmd == "config":
                value = manager.config()
            elif args.cmd == "token":
                token_path = manager.home / "http-token"
                fd = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as output:
                    output.write(secrets.token_urlsafe(48) + "\n")
                value = {"token_file": str(token_path), "note": "Keep private; token value is not printed."}
            elif args.cmd in {"check", "update"}:
                if args.cmd == "check":
                    value = check_update(manager.home, force=args.force, offline=args.offline)
                else:
                    metadata, url = latest()
                    active = manager.active()
                    if active and tuple(map(int, active["version"].split("."))) >= tuple(map(int, metadata["version"].split("."))):
                        value = {"status": "current", "installed": active, "available": metadata["version"]}
                    else:
                        with tempfile.TemporaryDirectory(prefix="ue-update-") as folder:
                            archive = Path(folder) / metadata["archive"]
                            archive.write_bytes(download(url))
                            value = manager.install(archive, metadata["sha256"])
            elif args.cmd == "capabilities":
                from ue_mcp.runtime import capabilities
                store = Store(manager.home)
                try:
                    value = capabilities(store, args.instance)
                finally:
                    store.close()
            elif args.cmd == "doctor":
                store = Store(manager.home)
                try:
                    active = manager.active()
                    if active:
                        verify(manager.home / "packages" / active["package"])
                    value = {"runtime_version": VERSION, "active": active, "package_root": str(ROOT),
                             "python": platform.python_version(), "platform": sys.platform,
                             "gh_available": bool(shutil.which("gh")),
                             "instances": list(store.profiles()), "contribution": Queue(store).config(),
                             "reconnect_required": local_version(manager)["reconnect_required"],
                             "update": check_update(manager.home, offline=True),
                             "live_ue_verified": False}
                finally:
                    store.close()
        print(json.dumps(value, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
