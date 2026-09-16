#!/usr/bin/env bash
# Build the GraalVM-patched LLVM toolchain for one platform.
#
#   build.sh <platform> <src-dir> <install-dir> [crt-install-dir]
#
# platform: linux-amd64 | darwin-aarch64 | windows-amd64
# The build directory is ./build-llvm (and ./build-crt on linux) relative to $PWD.
set -euo pipefail

PLATFORM=${1:?platform}
SRC=${2:?llvm-project source dir}
INSTALL=${3:?install dir}
CRT_INSTALL=${4:-${INSTALL}-crt}

case "$PLATFORM" in
  windows-amd64)
    # Git Bash: give cmake clean forward-slash Windows paths.
    SRC=$(cygpath -m "$SRC"); INSTALL=$(cygpath -m "$INSTALL") ;;
  linux-amd64|darwin-aarch64) ;;
  *) echo "unknown platform: $PLATFORM" >&2; exit 2 ;;
esac

LAUNCHER=()
if command -v sccache >/dev/null 2>&1; then
  LAUNCHER=(-DCMAKE_C_COMPILER_LAUNCHER=sccache -DCMAKE_CXX_COMPILER_LAUNCHER=sccache)
fi

COMMON=(
  -G Ninja
  -DCMAKE_BUILD_TYPE=Release
  -DCMAKE_INSTALL_PREFIX="$INSTALL"
  -DLLVM_ENABLE_PROJECTS="clang;lld"
  -DLLVM_TARGETS_TO_BUILD="X86;AArch64"
  -DLLVM_ENABLE_ASSERTIONS=OFF
  -DLLVM_INCLUDE_TESTS=OFF
  -DLLVM_INCLUDE_DOCS=OFF
  -DLLVM_INCLUDE_EXAMPLES=OFF
  -DLLVM_INCLUDE_BENCHMARKS=OFF
  -DCLANG_INCLUDE_TESTS=OFF
  -DCLANG_INCLUDE_DOCS=OFF
  -DCLANG_ENABLE_STATIC_ANALYZER=OFF
  -DCLANG_ENABLE_ARCMT=OFF
  -DLLVM_ENABLE_ZLIB=OFF
  -DLLVM_ENABLE_ZSTD=OFF
  -DLLVM_ENABLE_LIBXML2=OFF
  -DLLVM_ENABLE_LIBEDIT=OFF
  -DLLVM_ENABLE_LIBPFM=OFF
  -DLLVM_ENABLE_BINDINGS=OFF
  -DLLVM_PARALLEL_LINK_JOBS=2
  "${LAUNCHER[@]}"
)

# Runtime options are forwarded to the bootstrapping runtimes build by prefix.
RUNTIMES=(
  -DLLVM_ENABLE_RUNTIMES="compiler-rt;libunwind;libcxxabi;libcxx"
  -DCOMPILER_RT_BUILD_BUILTINS=ON
  -DCOMPILER_RT_BUILD_CRT=ON
  -DCOMPILER_RT_BUILD_SANITIZERS=OFF
  -DCOMPILER_RT_BUILD_XRAY=OFF
  -DCOMPILER_RT_BUILD_LIBFUZZER=OFF
  -DCOMPILER_RT_BUILD_PROFILE=OFF
  -DCOMPILER_RT_BUILD_MEMPROF=OFF
  -DCOMPILER_RT_BUILD_ORC=OFF
  -DCOMPILER_RT_BUILD_GWP_ASAN=OFF
  -DCOMPILER_RT_BUILD_CTX_PROFILE=OFF
  -DLIBCXX_INCLUDE_TESTS=OFF
  -DLIBCXX_INCLUDE_BENCHMARKS=OFF
  -DLIBCXXABI_INCLUDE_TESTS=OFF
  -DLIBUNWIND_INCLUDE_TESTS=OFF
)

case "$PLATFORM" in
  linux-amd64)
    PLATFORM_ARGS=(
      -DCMAKE_C_COMPILER=gcc -DCMAKE_CXX_COMPILER=g++
      -DLLVM_USE_LINKER=lld
      "${RUNTIMES[@]}"
    ) ;;
  darwin-aarch64)
    PLATFORM_ARGS=(
      -DCMAKE_C_COMPILER=clang -DCMAKE_CXX_COMPILER=clang++
      -DCMAKE_OSX_DEPLOYMENT_TARGET=11.0
      -DCOMPILER_RT_ENABLE_IOS=OFF -DCOMPILER_RT_ENABLE_WATCHOS=OFF -DCOMPILER_RT_ENABLE_TVOS=OFF
      -DCOMPILER_RT_ENABLE_MACCATALYST=OFF
      -DDARWIN_osx_ARCHS=arm64 -DDARWIN_osx_BUILTIN_ARCHS=arm64
      "${RUNTIMES[@]}"
    ) ;;
  windows-amd64)
    PLATFORM_ARGS=(
      -DCMAKE_C_COMPILER=cl -DCMAKE_CXX_COMPILER=cl
      -DLLVM_ENABLE_DIA_SDK=OFF
    ) ;;
esac

echo "== configure ($PLATFORM)"
cmake -S "$SRC/llvm" -B build-llvm "${COMMON[@]}" "${PLATFORM_ARGS[@]}"
echo "== build + install"
cmake --build build-llvm --target install
echo "== installed tools"
ls "$INSTALL/bin" | head -50

if [ "$PLATFORM" = linux-amd64 ]; then
  echo "== standalone compiler-rt builtins (non per-target layout)"
  MAJOR=$("$INSTALL/bin/llvm-config" --version | cut -d. -f1)
  cmake -S "$SRC/runtimes" -B build-crt -G Ninja \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX="$CRT_INSTALL/stage" \
    -DCMAKE_C_COMPILER="$INSTALL/bin/clang" -DCMAKE_CXX_COMPILER="$INSTALL/bin/clang++" -DCMAKE_ASM_COMPILER="$INSTALL/bin/clang" \
    -DLLVM_ENABLE_RUNTIMES=compiler-rt \
    -DLLVM_ENABLE_PER_TARGET_RUNTIME_DIR=OFF \
    -DCOMPILER_RT_DEFAULT_TARGET_ONLY=ON \
    -DCOMPILER_RT_BUILD_BUILTINS=ON -DCOMPILER_RT_BUILD_CRT=ON \
    -DCOMPILER_RT_BUILD_SANITIZERS=OFF -DCOMPILER_RT_BUILD_XRAY=OFF -DCOMPILER_RT_BUILD_LIBFUZZER=OFF \
    -DCOMPILER_RT_BUILD_PROFILE=OFF -DCOMPILER_RT_BUILD_MEMPROF=OFF -DCOMPILER_RT_BUILD_ORC=OFF \
    -DCOMPILER_RT_BUILD_GWP_ASAN=OFF -DCOMPILER_RT_BUILD_CTX_PROFILE=OFF \
    "${LAUNCHER[@]}"
  cmake --build build-crt --target install
  DEST="$CRT_INSTALL/lib/clang/$MAJOR/lib/linux"
  mkdir -p "$DEST"
  for f in libclang_rt.builtins-x86_64.a clang_rt.crtbegin-x86_64.o clang_rt.crtend-x86_64.o; do
    src=$(find "$CRT_INSTALL/stage" -name "$f" | head -1)
    [ -n "$src" ] || { echo "missing $f in compiler-rt build" >&2; find "$CRT_INSTALL/stage" -type f | head; exit 1; }
    cp "$src" "$DEST/"
  done
  rm -rf "$CRT_INSTALL/stage"
  find "$CRT_INSTALL" -type f
fi
