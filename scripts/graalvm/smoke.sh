#!/usr/bin/env bash
# Smoke-test a GraalVM home built by graalvm.yml.
#
#   smoke.sh <graalvm-home> <work-dir>
#
# Checks: java, native-image, lli, compiling C with the bundled toolchain and
# running it on Sulong, and (when the llvm-backend tool exists) building a
# Java hello world with `native-image --tool:llvm-backend`.
set -euo pipefail
export MSYS_NO_PATHCONV=1   # Git Bash on Windows: do not mangle -cp / --tool: arguments

H=${1:?graalvm home}
W=${2:?work dir}
mkdir -p "$W"; W=$(cd "$W" && pwd)
cd "$W"

exe() {  # exe <dir> <name>: first existing of name, name.exe, name.cmd
  local d=$1 n=$2 c
  for c in "$n" "$n.exe" "$n.cmd"; do
    if [ -e "$d/$c" ]; then echo "$d/$c"; return 0; fi
  done
  echo "missing $n in $d" >&2; ls "$d" >&2; return 1
}

JAVA=$(exe "$H/bin" java); NI=$(exe "$H/bin" native-image); LLI=$(exe "$H/bin" lli); JAVAC=$(exe "$H/bin" javac)

echo "== java --version";          "$JAVA" --version
echo "== native-image --version";  "$NI" --version
echo "== lli --version";           "$LLI" --version

echo "== Sulong: compile C with the bundled toolchain and run it"
TC=$("$LLI" --print-toolchain-path | tr -d '\r')
echo "toolchain: $TC"; ls "$TC/bin"
CLANG=$(exe "$TC/bin" clang)
cat > hello.c <<'EOC'
#include <stdio.h>
int main(void) { printf("Hello from Sulong\n"); return 0; }
EOC
"$CLANG" hello.c -o hello.exe
"$LLI" hello.exe | tee lli.out
grep -q 'Hello from Sulong' lli.out

if [ -d "$H/lib/svm/tools/llvm-backend" ] || [ -d "$H/lib/svm/macros/llvm-backend" ]; then
  echo "== Native Image LLVM backend"
  cat > Hello.java <<'EOJ'
public class Hello { public static void main(String[] a) { System.out.println("Hello from the LLVM backend"); } }
EOJ
  "$JAVAC" Hello.java
  "$NI" --tool:llvm-backend -cp . Hello -o hello-llvm
  ./hello-llvm | tee ni.out
  grep -q 'Hello from the LLVM backend' ni.out
  echo "LLVM backend: tested"
else
  echo "LLVM backend: not available in this build"
fi
echo "SMOKE OK"
