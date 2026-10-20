#!/usr/bin/env python3
"""Serve the same UE runtime to any compatible MCP client."""
import argparse
from pathlib import Path
import sys

from ue_mcp.server import HTTPServer, stdio


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transport", choices=("stdio", "http"), default="stdio")
    parser.add_argument("--state-dir")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--token-file", help="private bearer token file, required for HTTP")
    args = parser.parse_args()
    try:
        if args.transport == "stdio":
            stdio(sys.stdin.buffer, sys.stdout.buffer, args.state_dir)
        else:
            if not args.token_file:
                parser.error("--token-file is required for HTTP; never expose the UE port directly")
            token = Path(args.token_file).read_text(encoding="utf-8").strip()
            with HTTPServer(("127.0.0.1", args.port), token, args.state_dir) as server:
                print("Unreal MCP bridge listening locally on port " + str(server.server_port), file=sys.stderr)
                server.serve_forever()
        return 0
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
