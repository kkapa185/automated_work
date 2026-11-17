"""Command line interface: ``catalog build`` and ``catalog serve``."""
from __future__ import annotations

import argparse
import sys

from .catalog import HubError, build_catalog, write_catalog


def make_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="catalog", description="Challenge Project catalog and explorer")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="parse the hub and write projects.json")
    b.add_argument("hub")
    b.add_argument("-o", "--output", required=True)
    s = sub.add_parser("serve", help="serve the API and Project Explorer UI")
    s.add_argument("hub")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--host", default="127.0.0.1")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    try:
        projects = build_catalog(args.hub)
    except HubError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if args.cmd == "build":
        try:
            write_catalog(projects, args.output)
        except OSError as e:
            print(f"error: cannot write {args.output}: {e}", file=sys.stderr)
            return 1
        print(f"wrote {len(projects)} projects to {args.output}", file=sys.stderr)
        return 0
    from .server import make_server
    try:
        httpd = make_server(projects, args.host, args.port)
    except OSError as e:
        print(f"error: cannot listen on {args.host}:{args.port}: {e}", file=sys.stderr)
        return 1
    host, port = httpd.server_address[:2]
    print(f"serving {len(projects)} projects on http://{host}:{port}/", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0
