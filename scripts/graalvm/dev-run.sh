#!/usr/bin/env bash
# Build one test program with the Native Image LLVM backend and check its output.
#
#   dev-run.sh <graalvm-home> <program-dir> <work-dir> [extra native-image args...]
#
# <program-dir> holds *.java (main class = directory name capitalised, e.g. hello -> Hello)
# and expected.txt; every line of expected.txt must appear in the program's stdout.
set -euo pipefail
export MSYS_NO_PATHCONV=1
H=${1:?graalvm home}; P=${2:?program dir}; W=${3:?work dir}; shift 3
P=$(cd "$P" && pwd); mkdir -p "$W"; W=$(cd "$W" && pwd)

exe() { local d=$1 n=$2 c; for c in "$n" "$n.exe" "$n.cmd"; do [ -e "$d/$c" ] && { echo "$d/$c"; return 0; }; done; echo "missing $n in $d" >&2; ls "$d" >&2; return 1; }
JAVAC=$(exe "$H/bin" javac); NI=$(exe "$H/bin" native-image)

name=$(basename "$P"); main="$(tr '[:lower:]' '[:upper:]' <<<"${name:0:1}")${name:1}"
mkdir -p "$W/classes" "$W/tmp"
echo "== javac"; "$JAVAC" -d "$W/classes" "$P"/*.java
echo "== native-image (LLVM backend)"
unset NATIVE_IMAGE_EXPERIMENTAL_OPTIONS_ARE_FATAL
"$NI" -H:+UnlockExperimentalVMOptions --tool:llvm-backend \
  -H:TempDirectory="$W/tmp" -H:+ReportExceptionStackTraces \
  "$@" -cp "$W/classes" "$main" -o "$W/app"
echo "== run"
app="$W/app"; [ -e "$app" ] || app="$W/app.exe"
"$app" > "$W/stdout.txt" 2> "$W/stderr.txt" || { echo "program exited with $?"; cat "$W/stdout.txt" "$W/stderr.txt"; exit 1; }
cat "$W/stdout.txt"
while IFS= read -r line; do
  [ -z "$line" ] && continue
  grep -qF -- "$line" "$W/stdout.txt" || { echo "missing expected line: $line" >&2; exit 1; }
done < "$P/expected.txt"
echo "DEV-RUN OK"
