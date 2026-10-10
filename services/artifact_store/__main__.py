"""Offline pack/verify/plan commands; no Bucket client import or network calls."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import build_pack, verify_pack


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    pack = sub.add_parser("pack", help="copy explicitly selected sanitized structured files")
    pack.add_argument("--source", required=True)
    pack.add_argument("--output", required=True)
    pack.add_argument("--metadata", required=True, help="completed-run metadata JSON path")
    pack.add_argument("--file", action="append", required=True, help="exact allowlisted filename; repeat")
    verify = sub.add_parser("verify", help="verify an existing local pack")
    verify.add_argument("--pack", required=True)
    plan = sub.add_parser("plan", help="print offline remote object plan without connecting")
    plan.add_argument("--pack", required=True)
    args = parser.parse_args()
    if args.command == "pack":
        manifest = build_pack(args.source, args.output,
                              json.loads(Path(args.metadata).read_text(encoding="utf-8")), args.file)
        result = {"status": "packed", "prefix": manifest["remote_prefix"], "files": manifest["files"]}
    else:
        manifest = verify_pack(args.pack)
        result = {"status": "verified_local", "prefix": manifest["remote_prefix"]}
        if args.command == "plan":
            result = {"status": "offline_dry_run", "prefix": manifest["remote_prefix"],
                      "files": [manifest["remote_prefix"] + e["path"] for e in manifest["files"]]
                      + [manifest["remote_prefix"] + "manifest.json"]}
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
