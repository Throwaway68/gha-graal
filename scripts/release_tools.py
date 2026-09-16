#!/usr/bin/env python3
"""Release helpers for the gha-graal workflows.

  release_tools.py manifest <dir> --version <v>
      Print a JSON manifest with sha512 digests of every file in <dir>
      (manifest.json itself is skipped).

  release_tools.py urlrewrites <manifest.json> <base_url>
      Print mx URL rewrite rules (for MX_URLREWRITES) that redirect graal's
      downloads from https://lafo.ssw.uni-linz.ac.at/pub/llvm to
      <base_url>/<asset>, with the manifest digest as override.
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

LAFO_HOST = "https://lafo.ssw.uni-linz.ac.at/pub/llvm"
# Oracle's versions look like 22.1.8-4-g1d96596a53-bg6891668b1e; ours like
# 22.1.8-graal.1. Both start with a digit, which is what keeps
# "llvm-<v>-darwin-aarch64" from matching "llvm-lldonly-<v>-darwin-aarch64".
VERSION_RE = r"[0-9][^/]*"


def sha512_of(path: Path) -> str:
    h = hashlib.sha512()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(1 << 20), b""):
            h.update(chunk)
    return "sha512:" + h.hexdigest()


def build_manifest(directory: Path, version: str) -> dict:
    files = {}
    for p in sorted(Path(directory).iterdir()):
        if p.is_file() and p.name != "manifest.json":
            files[p.name] = sha512_of(p)
    return {"version": version, "files": files}


def lafo_pattern(name: str, version: str) -> str:
    if version not in name:
        raise ValueError(f"{name!r} does not contain version {version!r}")
    head, tail = name.split(version, 1)
    return "^" + re.escape(LAFO_HOST + "/" + head) + VERSION_RE + re.escape(tail) + "$"


def urlrewrites(manifest: dict, base_url: str) -> list:
    version = manifest["version"]
    base = base_url.rstrip("/")
    rules = []
    for name, digest in manifest["files"].items():
        rules.append({lafo_pattern(name, version): {"replacement": f"{base}/{name}", "digest": digest}})
    return rules


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("manifest")
    m.add_argument("directory", type=Path)
    m.add_argument("--version", required=True)
    u = sub.add_parser("urlrewrites")
    u.add_argument("manifest", type=Path)
    u.add_argument("base_url")
    args = ap.parse_args(argv)
    if args.cmd == "manifest":
        json.dump(build_manifest(args.directory, args.version), sys.stdout, indent=2)
    else:
        json.dump(urlrewrites(json.loads(args.manifest.read_text()), args.base_url), sys.stdout, indent=2)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
