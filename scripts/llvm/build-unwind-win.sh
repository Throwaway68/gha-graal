#!/usr/bin/env bash
# Build LLVM's libunwind in SEH mode for x86_64 Windows with the bundled clang.
#
#   build-unwind-win.sh <llvm-src-dir> <clang-install-dir> <out-dir>
#
# The library is compiled for x86_64-w64-windows-gnu (that target predefines __SEH__,
# which selects Unwind-seh.cpp) against the mingw-w64 UCRT headers from MSYS2, and
# installed as <out-dir>/lib/x86_64-w64-windows-gnu/libunwind.a plus a copy named
# unwind.lib (link.exe rejects the .a extension) and <out-dir>/include/*.h.
# Native Image links it into MSVC-built images as a plain COFF archive: nothing of
# the mingw CRT is used, only headers, so every undefined symbol must be resolvable
# against the UCRT (ucrt.lib via /MD), kernel32 or ntdll.
#
# Environment: MSYS2_ROOT (default C:/msys64), BUILD_DIR (default build-unwind).
set -euo pipefail

[ $# -eq 3 ] || { echo "usage: build-unwind-win.sh <llvm-src-dir> <clang-install-dir> <out-dir>" >&2; exit 2; }

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)

winpath() {  # cmake and clang want C:/... paths, not /c/... MSYS paths
  if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else printf '%s\n' "$1"; fi
}

SRC=$(winpath "$1")
CLANG=$(winpath "$2")
OUT=$(winpath "$3")
BUILD=${BUILD_DIR:-build-unwind}
MSYS=${MSYS2_ROOT:-C:/msys64}
SYSROOT=$MSYS/ucrt64
TRIPLE=x86_64-w64-windows-gnu

[ -d "$SRC/runtimes" ] || { echo "no runtimes/ under $SRC" >&2; exit 1; }
[ -d "$SRC/libunwind" ] || { echo "no libunwind/ under $SRC" >&2; exit 1; }
[ -x "$CLANG/bin/clang.exe" ] || { echo "no clang.exe under $CLANG/bin" >&2; exit 1; }

echo "== mingw-w64 UCRT headers ($SYSROOT)"
if [ -f "$SYSROOT/include/windows.h" ] && [ -f "$SYSROOT/include/ntstatus.h" ]; then
  echo "already installed"
else
  PKGS="mingw-w64-ucrt-x86_64-headers-git mingw-w64-ucrt-x86_64-crt-git"
  "$MSYS/usr/bin/bash.exe" -lc "pacman -S --noconfirm --needed $PKGS" ||
    { "$MSYS/usr/bin/bash.exe" -lc "pacman -Sy --noconfirm" &&
      "$MSYS/usr/bin/bash.exe" -lc "pacman -S --noconfirm --needed $PKGS"; }
fi
ls -l "$SYSROOT/include/windows.h" "$SYSROOT/include/ntstatus.h" "$SYSROOT/include/excpt.h" "$SYSROOT/include/winnt.h"

# -mno-stack-arg-probe: the gnu target otherwise calls ___chkstk_ms for frames over a
#   page, and that symbol lives in libgcc/compiler-rt, neither of which is linked here.
# -D__USE_MINGW_ANSI_STDIO=0: keeps fprintf out of mingw's __mingw_*printf replacements.
# -D_UCRT: selects the UCRT declarations in the mingw headers (matches Native Image's /MD).
FLAGS="-mno-stack-arg-probe -D__USE_MINGW_ANSI_STDIO=0 -D_UCRT"

echo "== configure"
rm -rf "$BUILD"
cmake -S "$SRC/runtimes" -B "$BUILD" -G Ninja \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX="$OUT" \
  -DLLVM_ENABLE_RUNTIMES=libunwind \
  -DLLVM_ENABLE_PER_TARGET_RUNTIME_DIR=ON \
  -DLLVM_DEFAULT_TARGET_TRIPLE=$TRIPLE \
  -DCMAKE_C_COMPILER="$CLANG/bin/clang.exe" \
  -DCMAKE_CXX_COMPILER="$CLANG/bin/clang++.exe" \
  -DCMAKE_ASM_COMPILER="$CLANG/bin/clang.exe" \
  -DCMAKE_C_COMPILER_TARGET=$TRIPLE \
  -DCMAKE_CXX_COMPILER_TARGET=$TRIPLE \
  -DCMAKE_ASM_COMPILER_TARGET=$TRIPLE \
  -DCMAKE_SYSROOT="$SYSROOT" \
  -DCMAKE_AR="$CLANG/bin/llvm-ar.exe" \
  -DCMAKE_RANLIB="$CLANG/bin/llvm-ranlib.exe" \
  -DCMAKE_TRY_COMPILE_TARGET_TYPE=STATIC_LIBRARY \
  -DCMAKE_C_FLAGS="$FLAGS" -DCMAKE_CXX_FLAGS="$FLAGS" -DCMAKE_ASM_FLAGS="$FLAGS" \
  -DLIBUNWIND_ENABLE_SHARED=OFF -DLIBUNWIND_ENABLE_STATIC=ON \
  -DLIBUNWIND_ENABLE_ASSERTIONS=OFF \
  -DLIBUNWIND_USE_COMPILER_RT=ON -DLIBUNWIND_ENABLE_CROSS_UNWINDING=OFF \
  -DLLVM_INCLUDE_TESTS=OFF \
  -DLIBUNWIND_INCLUDE_TESTS=OFF -DLIBUNWIND_INCLUDE_DOCS=OFF \
  -DLIBUNWIND_INSTALL_LIBRARY=ON -DLIBUNWIND_INSTALL_HEADERS=ON

echo "== build + install"
cmake --build "$BUILD" --target install

LIB=$(find "$OUT" -name libunwind.a | head -1)
[ -n "$LIB" ] || { echo "libunwind.a not produced" >&2; find "$OUT" -type f | head -50; exit 1; }
mkdir -p "$OUT/lib/$TRIPLE"
[ "$LIB" = "$OUT/lib/$TRIPLE/libunwind.a" ] || cp "$LIB" "$OUT/lib/$TRIPLE/libunwind.a"
LIB=$OUT/lib/$TRIPLE/libunwind.a

echo "== make the unwind COMDATs linkable by link.exe"
PY=$(command -v python3 || command -v python || true)
[ -n "$PY" ] || { echo "python is needed for coff-assoc-comdats.py" >&2; exit 1; }
"$PY" "$SCRIPT_DIR/coff-assoc-comdats.py" "$LIB"

# link.exe also accepts the .a extension, but Native Image's linker invocation
# builds library arguments as <name>.lib, so install the archive under that name too.
cp "$LIB" "$OUT/lib/$TRIPLE/unwind.lib"

mkdir -p "$OUT/include"
for h in unwind.h unwind_itanium.h libunwind.h __libunwind_config.h; do
  [ -f "$OUT/include/$h" ] || cp "$SRC/libunwind/include/$h" "$OUT/include/$h"
done
ls -l "$OUT/include"

NM="$CLANG/bin/llvm-nm.exe"
export LC_ALL=C
"$NM" --defined-only "$LIB" | awk 'NF>=3 && $2 ~ /^[A-Za-z]$/ {print $3}' | sort -u > "$OUT/libunwind-defined.txt"

echo "== defined symbols of interest"
missing=
for s in _Unwind_RaiseException _Unwind_Resume _Unwind_DeleteException _Unwind_Backtrace \
         _GCC_specific_handler _Unwind_GetLanguageSpecificData _Unwind_GetRegionStart \
         _Unwind_GetIP _Unwind_GetIPInfo _Unwind_SetIP _Unwind_GetGR _Unwind_SetGR; do
  if grep -qx "$s" "$OUT/libunwind-defined.txt"; then echo "  ok      $s"; else echo "  MISSING $s"; missing="$missing $s"; fi
done
[ -z "$missing" ] || { echo "libunwind.a lacks:$missing" >&2; exit 1; }

echo "== undefined symbols (archive-internal ones filtered out; the rest must come from ucrt/kernel32/ntdll)"
"$NM" --undefined-only "$LIB" | awk '$1=="U"||$1=="w"{print $2}' | sort -u > "$OUT/libunwind-undefined-raw.txt"
comm -23 "$OUT/libunwind-undefined-raw.txt" "$OUT/libunwind-defined.txt" | tee "$OUT/libunwind-undefined.txt"
if grep -Eq '^_*(_chkstk_ms|mingw_|gcc_personality|libgcc)' "$OUT/libunwind-undefined.txt"; then
  echo "libunwind.a references mingw/libgcc runtime symbols that the MSVC link cannot resolve" >&2
  exit 1
fi
echo "== libunwind.a: $LIB"
