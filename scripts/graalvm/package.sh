#!/usr/bin/env bash
# Package a GraalVM home as <out-dir>/<name>.tar.gz (linux/darwin) or <name>.zip (windows).
#
#   package.sh <graalvm-home> <name> <platform> <out-dir>
#
# The archive contains a single top-level directory <name>. On darwin the
# distribution root is the directory two levels above Contents/Home.
set -euo pipefail
HOME_DIR=${1:?graalvm home}
NAME=${2:?archive name}
PLATFORM=${3:?platform}
OUT=${4:?out dir}

HOME_DIR=$(cd "$HOME_DIR" && pwd -P)
ROOT=$HOME_DIR
case "$HOME_DIR" in */Contents/Home) ROOT=$(cd "$HOME_DIR/../.." && pwd -P) ;; esac

mkdir -p "$OUT"; OUT=$(cd "$OUT" && pwd)
STAGE=$(mktemp -d "${TMPDIR:-/tmp}/graalvm-stage.XXXXXX")
trap 'rm -rf "$STAGE"' EXIT
cp -R "$ROOT" "$STAGE/$NAME"

case "$PLATFORM" in
  linux-amd64|darwin-aarch64)
    tar -C "$STAGE" -czf "$OUT/$NAME.tar.gz" "$NAME" ;;
  windows-amd64)
    if command -v 7z >/dev/null 2>&1; then
      ( cd "$STAGE" && 7z a -tzip -bd -mx=5 "$OUT/$NAME.zip" "$NAME" >/dev/null )
    else
      ( cd "$STAGE" && zip -qr "$OUT/$NAME.zip" "$NAME" )
    fi ;;
  *) echo "unknown platform: $PLATFORM" >&2; exit 2 ;;
esac
ls -la "$OUT"
