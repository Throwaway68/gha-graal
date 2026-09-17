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
out=$(bash scripts/graalvm/dev-run.sh "$H" tests/programs/hello "$T/work" -H:Extra=1 2>&1)
echo "$out" | grep -q 'DEV-RUN OK' || { echo "$out"; echo "FAIL: no DEV-RUN OK"; exit 1; }
grep -q -- '--tool:llvm-backend' "$NI_LOG" || { echo "FAIL: --tool:llvm-backend not passed"; exit 1; }
grep -q -- '-H:Extra=1' "$NI_LOG" || { echo "FAIL: extra args not passed"; exit 1; }
grep -q 'Hello.java' "$JAVAC_LOG" || { echo "FAIL: javac not called on the program"; exit 1; }
# Output mismatch must fail
printf 'args=7\n' > "$T/expected.txt"; mkdir -p "$T/prog"; cp tests/programs/hello/Hello.java "$T/prog/"; cp "$T/expected.txt" "$T/prog/expected.txt"
if bash scripts/graalvm/dev-run.sh "$H" "$T/prog" "$T/work2" >/dev/null 2>&1; then echo "FAIL: mismatch not detected"; exit 1; fi
echo PASS
