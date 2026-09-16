#!/usr/bin/env bash
# Local test of scripts/llvm/package.sh on a fake install tree.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
V=1.0-test

# fake install tree
mkdir -p "$T/inst/bin" "$T/inst/lib/clang/22/lib/x86_64-unknown-linux-gnu" "$T/inst/include/lld" "$T/inst/include/llvm" "$T/inst/include/llvm-c"
for b in clang lld ld.lld ld64.lld lld-link wasm-ld llvm-tblgen llc; do echo "#!/bin/sh" > "$T/inst/bin/$b"; done
ln -s clang "$T/inst/bin/clang++"
echo x > "$T/inst/lib/libLLVM.a"; echo h > "$T/inst/include/llvm/a.h"
# fake crt tree
mkdir -p "$T/crt/lib/clang/22/lib/linux"; echo a > "$T/crt/lib/clang/22/lib/linux/libclang_rt.builtins-x86_64.a"
# fake source git repo
mkdir -p "$T/src/llvm"; echo s > "$T/src/llvm/CMakeLists.txt"
git -C "$T/src" init -q && git -C "$T/src" add -A && git -C "$T/src" -c user.name=t -c user.email=t@t commit -q -m init

fail() { echo "FAIL: $*" >&2; exit 1; }

# linux: three tarballs, no top-level dir
bash "$ROOT/scripts/llvm/package.sh" linux-amd64 "$V" "$T/inst" "$T/out-linux" "$T/src" "$T/crt"
[ -f "$T/out-linux/llvm-$V-linux-amd64.tar.gz" ] || fail "main tarball missing"
tar tzf "$T/out-linux/llvm-$V-linux-amd64.tar.gz" | grep -qx 'bin/clang' || fail "bin/clang not at root of main tarball"
tar tzf "$T/out-linux/llvm-$V-linux-amd64.tar.gz" | grep -q '^\./' && fail "main tarball has ./ prefix"
tar tzf "$T/out-linux/compiler-rt-$V-linux-amd64.tar.gz" | grep -qx 'lib/clang/22/lib/linux/libclang_rt.builtins-x86_64.a' || fail "crt layout"
tar tzf "$T/out-linux/llvm-src-$V.tar.gz" | grep -qx 'llvm/CMakeLists.txt' || fail "src tarball layout"
[ "$(ls "$T/out-linux" | wc -l)" -eq 3 ] || fail "linux should produce exactly 3 files"

# darwin: main + lldonly
bash "$ROOT/scripts/llvm/package.sh" darwin-aarch64 "$V" "$T/inst" "$T/out-mac"
L="$T/out-mac/llvm-lldonly-$V-darwin-aarch64.tar.gz"
[ -f "$L" ] || fail "lldonly missing"
for e in bin/lld bin/ld.lld bin/ld64.lld bin/lld-link bin/wasm-ld bin/llvm-tblgen include/llvm/a.h; do tar tzf "$L" | grep -qx "$e" || fail "lldonly lacks $e"; done
tar tzf "$L" | grep -qx 'bin/llc' && fail "lldonly must not contain llc"
[ "$(ls "$T/out-mac" | wc -l)" -eq 2 ] || fail "darwin should produce exactly 2 files"

# windows: main only
bash "$ROOT/scripts/llvm/package.sh" windows-amd64 "$V" "$T/inst" "$T/out-win"
[ "$(ls "$T/out-win" | wc -l)" -eq 1 ] || fail "windows should produce exactly 1 file"

echo "PASS test_package_llvm"
