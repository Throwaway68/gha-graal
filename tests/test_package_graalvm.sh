#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
fail() { echo "FAIL: $*" >&2; exit 1; }

# linux-style home
mkdir -p "$T/lin/graalvm-abc123-java25/bin"; echo j > "$T/lin/graalvm-abc123-java25/bin/java"
bash "$ROOT/scripts/graalvm/package.sh" "$T/lin/graalvm-abc123-java25" graalvm-test-linux-amd64 linux-amd64 "$T/out"
tar tzf "$T/out/graalvm-test-linux-amd64.tar.gz" | grep -qx 'graalvm-test-linux-amd64/bin/java' || fail "linux layout"

# darwin-style home (Contents/Home)
mkdir -p "$T/mac/graalvm-abc123-java25/Contents/Home/bin"; echo j > "$T/mac/graalvm-abc123-java25/Contents/Home/bin/java"
bash "$ROOT/scripts/graalvm/package.sh" "$T/mac/graalvm-abc123-java25/Contents/Home" graalvm-test-darwin-aarch64 darwin-aarch64 "$T/out"
tar tzf "$T/out/graalvm-test-darwin-aarch64.tar.gz" | grep -qx 'graalvm-test-darwin-aarch64/Contents/Home/bin/java' || fail "darwin layout"

# windows-style home -> zip
mkdir -p "$T/win/graalvm-abc123-java25/bin"; echo j > "$T/win/graalvm-abc123-java25/bin/java.exe"
bash "$ROOT/scripts/graalvm/package.sh" "$T/win/graalvm-abc123-java25" graalvm-test-windows-amd64 windows-amd64 "$T/out"
[ -f "$T/out/graalvm-test-windows-amd64.zip" ] || fail "zip missing"
unzip -l "$T/out/graalvm-test-windows-amd64.zip" | grep -q 'graalvm-test-windows-amd64/bin/java.exe' || fail "zip layout"
echo "PASS test_package_graalvm"
