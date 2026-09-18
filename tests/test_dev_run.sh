#!/usr/bin/env bash
# Exercises scripts/graalvm/dev-run.sh against a fake GraalVM home whose
# javac/native-image are shell stubs. Checks argument plumbing and output matching.
set -euo pipefail
cd "$(dirname "$0")/.."
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
H=$T/home; mkdir -p "$H/bin"
cat > "$H/bin/javac" <<'EOF'
#!/usr/bin/env bash
echo "javac $*" >> "$JAVAC_LOG"; touch "${@: -1}"; exit 0
EOF
cat > "$H/bin/native-image" <<'EOF'
#!/usr/bin/env bash
echo "native-image $*" >> "$NI_LOG"
out=""; while [ $# -gt 0 ]; do [ "$1" = -o ] && out=$2; shift; done
printf '#!/usr/bin/env bash\necho "Hello from the LLVM backend on Fake"\necho "args=0"\n' > "$out"; chmod +x "$out"
EOF
chmod +x "$H/bin/javac" "$H/bin/native-image"
export JAVAC_LOG=$T/javac.log NI_LOG=$T/ni.log
out=$(bash scripts/graalvm/dev-run.sh "$H" tests/programs/hello "$T/work" -H:Extra=1 2>&1) \
  || { rc=$?; echo "$out"; echo "FAIL: dev-run exited $rc"; exit 1; }
echo "$out" | grep -q 'DEV-RUN OK' || { echo "$out"; echo "FAIL: no DEV-RUN OK"; exit 1; }
grep -q -- '--tool:llvm-backend' "$NI_LOG" || { echo "FAIL: --tool:llvm-backend not passed"; exit 1; }
grep -q -- '-H:Extra=1' "$NI_LOG" || { echo "FAIL: extra args not passed"; exit 1; }
grep -q 'Hello.java' "$JAVAC_LOG" || { echo "FAIL: javac not called on the program"; exit 1; }
# The relative program dir and work dir must reach the toolchain as absolute paths
# (native form: /... on unix, D:/... in Git Bash), never as "tests/programs/hello".
grep -qE 'javac -d (/|[A-Za-z]:/)' "$JAVAC_LOG" || { cat "$JAVAC_LOG"; echo "FAIL: work dir not absolute"; exit 1; }
grep -qE ' (/|[A-Za-z]:/)[^ ]*/Hello\.java' "$JAVAC_LOG" || { cat "$JAVAC_LOG"; echo "FAIL: program dir not absolute"; exit 1; }
grep -qE -- '-H:TempDirectory=(/|[A-Za-z]:/)' "$NI_LOG" || { cat "$NI_LOG"; echo "FAIL: temp dir not absolute"; exit 1; }
# Windows shape: launcher is native-image.cmd and the image is written as app.exe
H2=$T/home2; mkdir -p "$H2/bin"; cp "$H/bin/javac" "$H2/bin/javac"
cat > "$H2/bin/native-image.cmd" <<'EOF'
#!/usr/bin/env bash
echo "native-image $*" >> "$NI_LOG"
out=""; while [ $# -gt 0 ]; do [ "$1" = -o ] && out=$2; shift; done
printf '#!/usr/bin/env bash\necho "Hello from the LLVM backend on Fake"\necho "args=0"\n' > "$out.exe"; chmod +x "$out.exe"
EOF
chmod +x "$H2/bin/javac" "$H2/bin/native-image.cmd"
out=$(bash scripts/graalvm/dev-run.sh "$H2" tests/programs/hello "$T/work3" 2>&1) \
  || { rc=$?; echo "$out"; echo "FAIL: .cmd/app.exe dev-run exited $rc"; exit 1; }
echo "$out" | grep -q 'DEV-RUN OK' || { echo "$out"; echo "FAIL: no DEV-RUN OK for .cmd/app.exe"; exit 1; }
[ -x "$T/work3/app.exe" ] || { echo "FAIL: app.exe not produced/run"; exit 1; }
# Git Bash shape: where `pwd -W` works it must be preferred over plain `pwd`, so the
# toolchain gets D:/a/... instead of the MSYS form /d/a/... . Simulated with an exported
# `pwd` function that logs the -W call and still returns the real (unix) path.
export PWD_W_LOG=$T/pwdw.log; : > "$PWD_W_LOG"
pwd() { if [ "${1:-}" = "-W" ]; then echo used >> "$PWD_W_LOG"; builtin pwd; else builtin pwd; fi; }
export -f pwd
if bash -c 'pwd -W >/dev/null 2>&1' && [ -s "$PWD_W_LOG" ]; then
  : > "$PWD_W_LOG"
  out=$(bash scripts/graalvm/dev-run.sh "$H" tests/programs/hello "$T/work4" 2>&1) \
    || { rc=$?; echo "$out"; echo "FAIL: dev-run exited $rc under a pwd -W shell"; exit 1; }
  [ -s "$PWD_W_LOG" ] || { echo "FAIL: dev-run.sh ignores 'pwd -W' where it works"; exit 1; }
else
  echo "note: exported-function override unavailable here, skipping the pwd -W preference check"
fi
unset -f pwd
# CRLF on both sides must still match: on Windows the image prints \r\n and expected.txt is
# checked out with \r\n as well. This guards the normalisation, not the Windows failure itself -
# a GNU/BSD grep matches the raw pair anyway, so only Git Bash's grep ever rejected it.
H3=$T/home3; mkdir -p "$H3/bin"; cp "$H/bin/javac" "$H3/bin/javac"
cat > "$H3/bin/native-image" <<'EOF'
#!/usr/bin/env bash
echo "native-image $*" >> "$NI_LOG"
out=""; while [ $# -gt 0 ]; do [ "$1" = -o ] && out=$2; shift; done
printf '#!/usr/bin/env bash\nprintf "Hello from the LLVM backend on Fake\\r\\nargs=0\\r\\n"\n' > "$out"; chmod +x "$out"
EOF
chmod +x "$H3/bin/native-image"
mkdir -p "$T/progcrlf"; cp tests/programs/hello/Hello.java "$T/progcrlf/"; printf 'args=0\r\n' > "$T/progcrlf/expected.txt"
out=$(bash scripts/graalvm/dev-run.sh "$H3" "$T/progcrlf" "$T/work5" 2>&1) \
  || { rc=$?; echo "$out"; echo "FAIL: CRLF dev-run exited $rc"; exit 1; }
echo "$out" | grep -q 'DEV-RUN OK' || { echo "$out"; echo "FAIL: CRLF output not matched"; exit 1; }
# and a real mismatch must still fail with CRLF expectations
printf 'args=7\r\n' > "$T/progcrlf/expected.txt"
if bash scripts/graalvm/dev-run.sh "$H3" "$T/progcrlf" "$T/work6" >/dev/null 2>&1; then echo "FAIL: CRLF mismatch not detected"; exit 1; fi
# Native library, javac.flags and META-INF: a program dir with a *.c file must be compiled by the
# bundled clang ($H/lib/llvm/bin/clang) into one shared library named after the program, and the
# image must then be run with -D<name>.lib=<that library>. javac.flags is appended to javac and
# META-INF lands on the classpath so native-image finds the *-config.json files by itself.
H4=$T/home4; mkdir -p "$H4/bin" "$H4/lib/llvm/bin"; cp "$H/bin/javac" "$H4/bin/javac"
cat > "$H4/bin/native-image" <<'EOF'
#!/usr/bin/env bash
echo "native-image $*" >> "$NI_LOG"
out=""; while [ $# -gt 0 ]; do [ "$1" = -o ] && out=$2; shift; done
printf '#!/usr/bin/env bash\necho "app $*" >> "$APP_LOG"\necho "NATIVE OK"\n' > "$out"; chmod +x "$out"
EOF
cat > "$H4/lib/llvm/bin/clang" <<'EOF'
#!/usr/bin/env bash
echo "clang $*" >> "$CLANG_LOG"
out=""; while [ $# -gt 0 ]; do [ "$1" = -o ] && out=$2; shift; done
: > "$out"
EOF
chmod +x "$H4/bin/native-image" "$H4/lib/llvm/bin/clang"
export CLANG_LOG=$T/clang.log APP_LOG=$T/app.log
mkdir -p "$T/nat/x/META-INF/native-image/gha-graal/x"
printf 'public class X { public static void main(String[] a) {} }\n' > "$T/nat/x/X.java"
printf '/* nothing */\n' > "$T/nat/x/x.c"
printf '[]\n' > "$T/nat/x/META-INF/native-image/gha-graal/x/jni-config.json"
printf -- '--add-modules org.graalvm.nativeimage\n' > "$T/nat/x/javac.flags"
printf 'NATIVE OK\n' > "$T/nat/x/expected.txt"
out=$(bash scripts/graalvm/dev-run.sh "$H4" "$T/nat/x" "$T/work7" 2>&1) \
  || { rc=$?; echo "$out"; echo "FAIL: native-library dev-run exited $rc"; exit 1; }
echo "$out" | grep -q 'DEV-RUN OK' || { echo "$out"; echo "FAIL: no DEV-RUN OK for the native-library program"; exit 1; }
grep -qE -- '-shared|-dynamiclib' "$CLANG_LOG" || { cat "$CLANG_LOG"; echo "FAIL: clang not asked for a shared library"; exit 1; }
grep -qF -- "-I$H4/include" "$CLANG_LOG" || { cat "$CLANG_LOG"; echo "FAIL: JNI headers of the GraalVM under test not on the clang command line"; exit 1; }
grep -qE -- ' [^ ]*/x\.c ' "$CLANG_LOG" || { cat "$CLANG_LOG"; echo "FAIL: the program's *.c not compiled"; exit 1; }
grep -qE -- '-o [^ ]*/(lib)?x\.(so|dylib|dll)$' "$CLANG_LOG" || { cat "$CLANG_LOG"; echo "FAIL: library not named after the program"; exit 1; }
lib=$(sed -n 's/.* -o \(.*\)$/\1/p' "$CLANG_LOG"); [ -f "$lib" ] || { echo "FAIL: library $lib not produced"; exit 1; }
grep -qF -- "app -Dx.lib=$lib" "$APP_LOG" || { cat "$APP_LOG"; echo "FAIL: the image was not run with -Dx.lib=<library>"; exit 1; }
grep -q -- '--add-modules org.graalvm.nativeimage' "$JAVAC_LOG" || { cat "$JAVAC_LOG"; echo "FAIL: javac.flags not passed to javac"; exit 1; }
[ -f "$T/work7/classes/META-INF/native-image/gha-graal/x/jni-config.json" ] || { echo "FAIL: META-INF not copied to the classpath"; exit 1; }
# A program without a *.c file must still run with no extra arguments (the empty-array path, which
# is what bash 3.2 rejects under `set -u` without the ${arr[@]+"${arr[@]}"} idiom).
: > "$APP_LOG"
mkdir -p "$T/nat/plain"; cp tests/programs/hello/Hello.java "$T/nat/plain/"; printf 'NATIVE OK\n' > "$T/nat/plain/expected.txt"
out=$(bash scripts/graalvm/dev-run.sh "$H4" "$T/nat/plain" "$T/work8" 2>&1) \
  || { rc=$?; echo "$out"; echo "FAIL: dev-run exited $rc without a *.c file"; exit 1; }
grep -qx -- 'app ' "$APP_LOG" || { cat "$APP_LOG"; echo "FAIL: the image got arguments although the program has no *.c"; exit 1; }

# Output mismatch must fail
printf 'args=7\n' > "$T/expected.txt"; mkdir -p "$T/prog"; cp tests/programs/hello/Hello.java "$T/prog/"; cp "$T/expected.txt" "$T/prog/expected.txt"
if bash scripts/graalvm/dev-run.sh "$H" "$T/prog" "$T/work2" >/dev/null 2>&1; then echo "FAIL: mismatch not detected"; exit 1; fi
echo PASS
