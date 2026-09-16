#!/usr/bin/env bash
# Pack the LLVM install tree into the tarballs graal's suite.py expects.
#
#   package.sh <platform> <version> <install-dir> <out-dir> [src-git-dir] [crt-dir]
#
# All tarballs have bin/, lib/, include/ ... at their root (no top-level dir),
# matching Oracle's bundles on lafo.ssw.uni-linz.ac.at.
set -euo pipefail

PLATFORM=${1:?platform}
VERSION=${2:?version}
INSTALL=${3:?install dir}
OUT=${4:?out dir}
SRC=${5:-}
CRT=${6:-}

mkdir -p "$OUT"
OUT=$(cd "$OUT" && pwd)

pack_dir() {  # pack_dir <dir> <tarball>: archive the entries of <dir> at the tarball root
  local dir=$1 tarball=$2
  ( cd "$dir" && tar -czf "$tarball" -- * )
}

echo "== $PLATFORM: main bundle"
pack_dir "$INSTALL" "$OUT/llvm-$VERSION-$PLATFORM.tar.gz"

case "$PLATFORM" in
  linux-amd64)
    [ -n "$SRC" ] && [ -n "$CRT" ] || { echo "linux-amd64 needs <src-git-dir> and <crt-dir>" >&2; exit 2; }
    echo "== compiler-rt bundle"
    pack_dir "$CRT" "$OUT/compiler-rt-$VERSION-linux-amd64.tar.gz"
    echo "== source bundle"
    git -C "$SRC" archive --format=tar.gz -o "$OUT/llvm-src-$VERSION.tar.gz" HEAD
    ;;
  darwin-aarch64)
    echo "== lld-only bundle"
    ( cd "$INSTALL" && tar -czf "$OUT/llvm-lldonly-$VERSION-darwin-aarch64.tar.gz" \
        bin/lld bin/ld.lld bin/ld64.lld bin/lld-link bin/wasm-ld bin/llvm-tblgen include/lld include/llvm include/llvm-c )
    ;;
  windows-amd64) ;;
  *) echo "unknown platform: $PLATFORM" >&2; exit 2 ;;
esac

ls -la "$OUT"
