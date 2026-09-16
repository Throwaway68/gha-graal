# GraalVM 25.3.4.1 + LLVM 22.1.8 CI builds — design

Date: 2026-09-16

## Goal

Produce, on GitHub Actions, redistributable builds of

1. an LLVM 22.1.8 toolchain carrying the patches GraalVM needs, and
2. GraalVM CE built from the upstream `graal-25.3.4.1` tag with the
   LLVM.org toolchain component, the Sulong LLVM runtime and, where the
   graal build system registers it, the Native Image LLVM backend,

for linux-amd64, windows-amd64 and darwin-aarch64. Both workflows take git
refs as inputs so that later branches (for example a branch adding Windows
support to the LLVM backend) can be built without changing the workflows.

## Facts the design rests on

- `graal-25.3.4.1` pins `LLVM_ORG` to `22.1.8-4-g1d96596a53-bg6891668b1e`
  and downloads prebuilt bundles from `https://lafo.ssw.uni-linz.ac.at/pub/llvm`.
  The libraries are `LLVM_ORG` (per platform), `LLVM_ORG_COMPILER_RT_LINUX`
  (linux-amd64 only, used on all platforms), `LLVM_ORG_SRC` (source tarball,
  used by Sulong to build its bitcode libc++) in `sdk/mx.sdk/suite.py`, and
  `LLVM_LLD_STANDALONE` (darwin-aarch64 only) in `substratevm/mx.substratevm/suite.py`.
- The patches are in `sdk/llvm-patches/` at that tag: two native-image
  patches (AArch64 frame record option, statepoint compressed pointers) and
  two backports (compiler-rt rtsan build fix, flang-rt iso module). They
  apply on top of `llvmorg-22.1.8`.
- mx supports URL rewrites with digest overrides (`MX_URLREWRITES`, JSON
  list of `{pattern, replacement, sha512}`), so graal can be pointed at our
  bundles without editing suite files.
- The Native Image LLVM backend component (`svml`) is registered by
  `substratevm/mx.substratevm/mx_substratevm.py` only when not on Windows and
  not on darwin-aarch64 (GR-34811). The backend's feature class is limited to
  Linux and Darwin; there is no Windows code path.
- The JDK is `labsjdk-ce-latest` = `ce-25.0.4.1+1-jvmci-25.3-b22`, available
  for all three platforms from `graalvm/labs-openjdk` releases via
  `mx fetch-jdk`. mx version is `7.85.1` (from `common.json`).
- The account is on the GitHub free plan: standard hosted runners only
  (4 vCPU Linux/Windows, 3 vCPU macOS arm64), six-hour job limit, public
  repositories so minutes are free.

## Repositories and branches

| Repo | Ref | Content |
|------|-----|---------|
| `Throwaway68/gha-graal` (new, public) | `main` | Workflows, scripts, mx env file, this spec. |
| `Throwaway68/llvm-project` | `graal/22.1.8` | `llvmorg-22.1.8` + the four graal patches as commits. |
| `Throwaway68/graal` | `graal/25.3.4.1-ci` | `graal-25.3.4.1` + one commit removing the darwin-aarch64 half of the GR-34811 guard. |

The graal branch is optional input; the workflow builds any ref, including
the pristine tag (then macOS gets no backend).

## Workflow `llvm.yml`

Trigger: `workflow_dispatch` with inputs `llvm_ref` (default
`graal/22.1.8`) and `version` (default `22.1.8-graal.1`; used in asset
names and the release tag).

Matrix: `ubuntu-22.04` (linux-amd64), `windows-2022` (windows-amd64),
`macos-14` (darwin-aarch64).

Build configuration (all platforms):

- `LLVM_ENABLE_PROJECTS=clang;lld`
- `LLVM_TARGETS_TO_BUILD=X86;AArch64`
- `CMAKE_BUILD_TYPE=Release`, assertions off
- tests, docs, examples, benchmarks off for llvm and clang
- `LLVM_ENABLE_ZLIB=OFF`, `LLVM_ENABLE_ZSTD=OFF`, `LLVM_ENABLE_LIBXML2=OFF`,
  `LLVM_ENABLE_TERMINFO=OFF`, `LLVM_ENABLE_LIBEDIT=OFF` so binaries are
  relocatable
- `LLVM_PARALLEL_LINK_JOBS=2`
- sccache via `mozilla-actions/sccache-action` with the GitHub Actions cache
  backend

Linux and macOS additionally:

- `LLVM_ENABLE_RUNTIMES=compiler-rt;libcxx;libcxxabi;libunwind` (per-target
  runtime directory layout, matching Oracle's bundle)
- `CMAKE_OSX_DEPLOYMENT_TARGET=11.0` on macOS

Windows: MSVC toolchain via `ilammy/msvc-dev-cmd`, no runtimes (Oracle's
Windows bundle ships none). `LLVM_ENABLE_PER_TARGET_RUNTIME_DIR` irrelevant.

flang and MLIR are not built. Consequence: the `graalvm-native-flang`
launcher is not built into GraalVM (removed from the env file).

Extra artifacts:

- Linux: a second, small build of compiler-rt builtins only with
  `LLVM_ENABLE_PER_TARGET_RUNTIME_DIR=OFF`, packed as
  `compiler-rt-<version>-linux-amd64.tar.gz` with the layout
  `lib/clang/22/lib/linux/{libclang_rt.builtins-x86_64.a,clang_rt.crtbegin-x86_64.o,clang_rt.crtend-x86_64.o}`.
- Linux: `llvm-src-<version>.tar.gz`, the patched source tree (no `.git`),
  with a single top-level directory.
- macOS: `llvm-lldonly-<version>-darwin-aarch64.tar.gz` containing
  `bin/{lld,ld.lld,ld64.lld,lld-link,wasm-ld,llvm-tblgen}` and the
  `include/{lld,llvm,llvm-c}` directories.

Asset names: `llvm-<version>-<os>-<arch>.tar.gz` where os/arch are
`linux-amd64`, `windows-amd64`, `darwin-aarch64`. Tarballs have no
top-level directory (bin/, lib/, include/ at the root), like Oracle's.

Release job (needs all three): downloads the artifacts, computes
`manifest.json` (`{"version": ..., "files": {"<asset>": "<sha512>"}}`),
creates GitHub Release `llvm-<version>` in `gha-graal` with all assets and
the manifest.

## Workflow `graalvm.yml`

Trigger: `workflow_dispatch` with inputs `graal_ref` (default
`graal/25.3.4.1-ci`), `llvm_release` (default `llvm-22.1.8-graal.1`, a
release tag in `gha-graal`), `label` (default derived from the two refs).

Matrix: same three runners.

Steps per platform:

1. Checkout `gha-graal` (scripts) and `Throwaway68/graal` at `graal_ref`
   into `graal/`.
2. Read `mx_version` from `graal/common.json`, checkout `graalvm/mx` at
   that tag.
3. Python 3.10 or newer, cmake, ninja; on Windows MSVC via
   `ilammy/msvc-dev-cmd`.
4. `mx fetch-jdk --jdk-id labsjdk-ce-latest` into the workspace, export
   `JAVA_HOME`.
5. Download `manifest.json` of the LLVM release, run
   `scripts/make_urlrewrites.py` which emits `MX_URLREWRITES` JSON mapping
   the four lafo URL patterns (`llvm-{version}-<os>-<arch>.tar.gz`,
   `compiler-rt-{version}-linux-amd64.tar.gz`, `llvm-src-{version}.tar.gz`,
   `llvm-lldonly-{version}-darwin-aarch64.tar.gz`) to the release asset
   URLs with the manifest's sha512 digests. The pattern matches any
   `{version}` so any graal ref works.
6. `cd graal/vm && mx --env <gha-graal>/mx-env/ce-llvm-ci build`.
   The env file:
   - `DYNAMIC_IMPORTS=/sdk,/truffle,/compiler,/substratevm,/sulong`
   - `COMPONENTS=` CE base (`cmp,gvm,lg,ni,nic,nil,sdkni,svm,svmjdwp,svmt,svmsl,tflc,tflsm`)
     plus `llp,llrc,llrl,llrn,llrlf,antlr4,svml`
   - `NATIVE_IMAGES=lib:jvmcicompiler,lib:llvmvm,lib:native-image-agent,lib:native-image-diagnostics-agent,native-image,graalvm-native-binutil,graalvm-native-clang,graalvm-native-clang-cl,graalvm-native-clang++,graalvm-native-ld`
     (`lli` is a thin launcher over the `lib:llvmvm` language library)
   - `NON_REBUILDABLE_IMAGES=lib:jvmcicompiler`
   Since mx aborts on unknown component names, the workflow strips `svml`
   from the component list on platforms where `mx graalvm-components`
   does not list it (Windows always; macOS on the pristine tag).
7. Smoke tests, all must pass:
   - `java --version`, `native-image --version`
   - `lli --version`; compile `hello.c` with `<home>/lib/llvm/bin/clang`
     (Windows: `clang.exe`) and run the bitcode with `lli`
   - Linux and macOS when `svml` was built: build `Hello.java` with
     `native-image --tool:llvm-backend` and run the executable
8. Package: `graalvm-<label>-<os>-<arch>.tar.gz` (Linux, macOS, dereferenced
   symlinks preserved as Oracle does) or `.zip` (Windows). Upload as artifact.

Release job: creates GitHub Release `graalvm-<label>` in `gha-graal` with
the three archives and a `manifest.json` of sha512 digests, plus the build
inputs recorded in the release notes (graal ref and commit, LLVM release).

## Error handling

- Any failed step fails the job; the matrix does not fail fast, so the
  other platforms still produce artifacts and the release job is skipped
  unless all three succeeded.
- sccache misses only slow the build. A Windows LLVM job that hits the
  six-hour limit is rerun; sccache has stored what was compiled.
- If the LLVM backend smoke test fails on macOS, the job fails; the fallback
  is to build the pristine tag (no `svml` on macOS) and report the failure.
- If Sulong fails to build on Windows, the fallback is a Windows env file
  without the Sulong components (toolchain only); this is reported, not
  silently applied.

## Out of scope

- Windows support for the Native Image LLVM backend (needs new unwinding,
  partial-link and objcopy code paths; the user will do this on a branch).
- flang, MLIR, RISC-V or WebAssembly targets in the LLVM bundle.
- Reproducing Oracle's exact CMake configuration; only what graal consumes
  is matched (binary names, layout, per-target runtime dirs).
- Tests beyond smoke tests (no mx gates).

## Verification

Both workflows are dispatched for real. Done means: Release
`llvm-22.1.8-graal.1` with seven assets and a manifest, and Release
`graalvm-<label>` with three archives, each produced by a run whose smoke
tests passed. Run URLs go in the final report.
