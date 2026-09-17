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
# Absolute, toolchain-native paths: `pwd -W` gives the Windows form (D:/a/_temp/work) in Git Bash,
# which bash, javac.exe, native-image.cmd and cmd.exe all accept; elsewhere it fails and we use pwd.
abspath() { (cd "$1" && { pwd -W 2>/dev/null || pwd; }); }
P=$(abspath "$P"); mkdir -p "$W"; W=$(abspath "$W")

exe() { local d=$1 n=$2 c; for c in "$n" "$n.exe" "$n.cmd"; do [ -e "$d/$c" ] && { echo "$d/$c"; return 0; }; done; echo "missing $n in $d" >&2; ls "$d" >&2; return 1; }
JAVAC=$(exe "$H/bin" javac); NI=$(exe "$H/bin" native-image)

# Best-effort Windows diagnostics for the LLVM backend, printed whether or not the build
# succeeded: where the code-section markers and the SEH personality glue ended up in
# llvm.obj, the layout of its .text$svm* sections, and the image's headers. Everything is
# optional - a missing tool or object silently prints nothing - so this never fails a run.
win_diag() {
  case "$(uname -s 2>/dev/null)" in MINGW*|MSYS*|CYGWIN*) ;; *) return 0;; esac
  echo "== diagnostics (windows)"
  local obj bin
  obj=$(ls "$W"/tmp/*/llvm/llvm.obj 2>/dev/null | head -1) || true
  bin=$H/lib/llvm/bin
  if [ -n "$obj" ] && { [ -e "$bin/llvm-nm" ] || [ -e "$bin/llvm-nm.exe" ]; }; then
    echo "-- markers and SEH glue in $obj"
    "$bin/llvm-nm" "$obj" 2>&1 | grep -E '__svm_code_section|__svm_text_end|__svm_seh_personality' || true
    echo "-- .text sections of $obj"
    "$bin/llvm-readobj" --section-headers "$obj" 2>&1 \
      | grep -E 'Name: \.text|VirtualSize|RawDataSize|Alignment' | head -60 || true
  fi
  if [ -e "$app" ] && command -v dumpbin >/dev/null 2>&1; then
    echo "-- dumpbin /headers $app"
    dumpbin /nologo /headers "$app" 2>&1 | head -80 || true
  fi
}

name=$(basename "$P"); main="$(tr '[:lower:]' '[:upper:]' <<<"${name:0:1}")${name:1}"
mkdir -p "$W/classes" "$W/tmp"
echo "== javac"; "$JAVAC" -d "$W/classes" "$P"/*.java
echo "== native-image (LLVM backend)"
unset NATIVE_IMAGE_EXPERIMENTAL_OPTIONS_ARE_FATAL
ni=0
"$NI" -H:+UnlockExperimentalVMOptions --tool:llvm-backend \
  -H:TempDirectory="$W/tmp" -H:+ReportExceptionStackTraces \
  "$@" -cp "$W/classes" "$main" -o "$W/app" || ni=$?
# app.exe first: MSYS's stat() appends .exe by itself, so `[ -e "$W/app" ]` is true on
# Windows too and dumpbin would then be handed an extension-less path it cannot open.
app="$W/app.exe"; [ -e "$app" ] || app="$W/app"
win_diag
[ "$ni" -eq 0 ] || { echo "native-image exited with $ni"; exit "$ni"; }
echo "== run"
"$app" > "$W/stdout.txt" 2> "$W/stderr.txt" || { echo "program exited with $?"; cat "$W/stdout.txt" "$W/stderr.txt"; exit 1; }
cat "$W/stdout.txt"
# Compare without carriage returns: the program prints CRLF on Windows, and expected.txt
# arrives there with CRLF as well (the runner checks out with core.autocrlf), while grep
# strips neither consistently.
tr -d '\r' < "$W/stdout.txt" > "$W/stdout.lf"
while IFS= read -r line; do
  line=${line%$'\r'}
  [ -z "$line" ] && continue
  grep -qF -- "$line" "$W/stdout.lf" || { echo "missing expected line: $line" >&2; exit 1; }
done < "$P/expected.txt"
echo "DEV-RUN OK"
