#!/usr/bin/env python3
"""MCP calls with explicit instance routing and managed write ownership."""
import argparse
import json
from pathlib import Path
import sys

from ue_mcp.instances import InstanceError, Store, process_identity
from ue_mcp.transport import Client, MCPError, READ_TOOLS, TransportError


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--tool")
    group.add_argument("--script", dest="script_path")
    ap.add_argument("--toolset")
    values = ap.add_mutually_exclusive_group()
    values.add_argument("--args")
    values.add_argument("--args-file")
    ap.add_argument("--out", dest="out_file")
    ap.add_argument("--url")
    ap.add_argument("--instance")
    ap.add_argument("--task-id")
    ap.add_argument("--state-dir")
    ap.add_argument("--timeout", type=float, default=120)
    args = ap.parse_args()
    store = Store(args.state_dir)
    writing = args.script_path or args.tool not in READ_TOOLS
    try:
        profile = store.resolve(args.instance, args.url)
        if not 1 <= args.timeout <= 120:
            raise InstanceError("Timeout must be 1-120 seconds (below the task lease duration)")
        if args.script_path:
            tool, toolset = "execute_tool_script", "editor_toolset.toolsets.programmatic.ProgrammaticToolset"
            arguments = {"script": Path(args.script_path).read_text(encoding="utf-8-sig")}
        else:
            tool, toolset = args.tool, args.toolset
            arguments = json.loads(Path(args.args_file).read_text(encoding="utf-8-sig")
                                   if args.args_file else args.args or "{}")
        if not isinstance(arguments, dict):
            raise ValueError("Tool arguments must be a JSON object")
        if writing:
            with store.write_guard(profile, args.task_id) as identity:
                with Client(profile["url"], timeout=args.timeout) as client:
                    # Re-check after initialize: a port may have changed owner during the handshake.
                    if process_identity(profile["url"], profile["project"]) != identity:
                        raise InstanceError("Editor changed during initialize; no write was sent")
                    result = client.call(tool, arguments, toolset)
        else:
            with Client(profile["url"], timeout=args.timeout) as client:
                result = client.call(tool, arguments, toolset)
        text = json.dumps({"jsonrpc": "2.0", "result": result}, ensure_ascii=False)
        if args.out_file:
            Path(args.out_file).write_text(text, encoding="utf-8")
            print("OK -> {}".format(args.out_file))
        else:
            print(text)
        return 0
    except TransportError as error:
        print("{}{}".format(error, "; write outcome may be UNKNOWN; read back before retrying"
                           if writing else ""), file=sys.stderr)
        return 4 if writing else 2
    except (MCPError, InstanceError, ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 2
    finally:
        store.close()


if __name__ == "__main__":
    sys.exit(main())
