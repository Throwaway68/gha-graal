# gha-graal

GitHub Actions builds of a GraalVM-patched LLVM 22.1.8 toolchain and GraalVM CE 25.3.4.1
(LLVM.org toolchain, Sulong LLVM runtime, Native Image LLVM backend) for
linux-amd64, windows-amd64 and darwin-aarch64. Design: `docs/superpowers/specs/2026-09-16-graal-llvm-ci-design.md`.

## Inputs

| Repo | Branch | What |
|------|--------|------|
| `Throwaway68/llvm-project` | `graal/22.1.8` | llvmorg-22.1.8 + the four patches from graal's `sdk/llvm-patches` |
| `Throwaway68/llvm-project` | `graal/22.1.8-win` | the above + `CallingConv::GRAAL` is Win64 on Windows (see below) |
| `Throwaway68/graal` | `graal/25.3.4.1-ci` | graal-25.3.4.1 + LLVM backend registered on darwin-aarch64 |
| `Throwaway68/graal` | `graal/25.3.4.1-win-llvm` | graal-25.3.4.1 + the Native Image LLVM backend on windows-amd64 (hello world green, see the journal) |

## Workflows

**LLVM toolchain** (`llvm.yml`): `gh workflow run llvm.yml -f llvm_ref=graal/22.1.8 -f version=22.1.8-graal.2`.
Publishes release `llvm-<version>` with `llvm-<version>-<platform>.tar.gz`,
`compiler-rt-<version>-linux-amd64.tar.gz`, `llvm-src-<version>.tar.gz`,
`llvm-lldonly-<version>-darwin-aarch64.tar.gz` and `manifest.json` (sha512). The release is
created as a draft, each asset is uploaded on its own with retries and verified against the
local file, and the draft flag is cleared last - uploads.github.com returns HTTP 500 often
enough on the ~1 GB bundles that a single `gh release create <tag> assets/*` loses the whole
release. An existing published release of the same tag fails the job instead of being touched.
The windows-amd64 bundle also carries libunwind built in SEH mode for
`x86_64-w64-windows-gnu` (`lib/x86_64-w64-windows-gnu/libunwind.a`, the same archive as
`unwind.lib`, and `include/unwind.h`), which the Native Image LLVM backend links into images.
Release `llvm-22.1.8-graal.3` is the same toolchain built from `graal/22.1.8-win`, whose one extra
commit makes `X86Subtarget::isCallingConvWin64` answer true for `CallingConv::GRAAL`: without it a
GraalVM-convention function on Win64 gets the Win64 argument registers but no 32-byte home space, so
C callers and every entry point with more than four arguments disagree about the fifth one. Nothing
changes off Windows. The Windows LLVM backend needs that release.

**GraalVM** (`graalvm.yml`): `gh workflow run graalvm.yml -f graal_ref=graal/25.3.4.1-ci -f llvm_release=llvm-22.1.8-graal.1`.
Builds any graal ref against the LLVM release: graal's downloads from
`lafo.ssw.uni-linz.ac.at/pub/llvm` are redirected with `MX_URLREWRITES`
(pattern + digest override), so no suite file is edited. Publishes release
`graalvm-<label>` with a `.tar.gz` per Unix platform, a `.zip` for Windows,
and `manifest.json`.

**GraalVM dev** (`graalvm-dev.yml`): `gh workflow run graalvm-dev.yml -f graal_ref=graal/25.3.4.1-win-llvm -f llvm_release=llvm-22.1.8-graal.3 -f platform=windows-amd64 -f program=hello`.
The iteration loop for the Windows backend port: one platform, no release. Builds the lean
`mx-env/ce-llvm-dev` GraalVM (compiler, SubstrateVM, native-image driver, LLVM backend tool,
LLVM.org toolchain; only `native-image` is built as a native launcher), then builds
`tests/programs/<program>` with `native-image --tool:llvm-backend` via
`scripts/graalvm/dev-run.sh` (extra arguments with `-f ni_args=...`) and uploads the
native-image work directory as artifact `dev-<platform>-<program>`. Every run builds the GraalVM
from scratch (~7.5 min on windows-amd64, ~5.5 min on linux-amd64); the only cache is mx's
downloads, keyed by platform, `llvm_release` and a hash of `common.json` and the `suite.py`
files, and saved right after the build so that a job failing at `dev-run` still keeps it. A
`mxbuild` cache was measured and dropped: a new graal commit reuses none of it, because mx
decides what to rebuild from file timestamps and a checkout stamps every source with the time of
the run - the workflow comments and the journal have the numbers.

**Shadowed jars** (`jars.yml`): `gh workflow run jars.yml -f version=1.5.7-graal.1`.
Rebuilds the JavaCPP 1.5.7 and LLVM 13.0.1-1.5.7 **windows-x86_64** platform jars from
Maven Central as graal-style *shadowed* jars (`org.bytedeco` relocated to
`com.oracle.svm.shadowed.org.bytedeco`, `open module
com.oracle.svm.shadowed.org.bytedeco.{javacpp,llvm}.windows.x86_64` in
`META-INF/versions/9`), the same shape as Oracle's linux/macOS jars. Publishes release
`jars-<version>` with the two jars and `manifest.json` (sha512); graal's
`LLVM_PLATFORM_SPECIFIC_SHADOWED` / `JAVACPP_PLATFORM_SPECIFIC_SHADOWED` windows-amd64
entries point at those URLs. The relocation itself is `scripts/jars/shadow.py`.

## Building your own branches

1. Push a branch to `Throwaway68/graal` (any base). Run `graalvm.yml` with `graal_ref=<branch>`.
   Forks do not carry upstream tags: to build an upstream tag, push it to the fork first
   (`git push <fork> refs/tags/<tag>:refs/tags/<tag>`); `graal-25.3.4.1` is already pushed.
2. To change LLVM, push a branch to `Throwaway68/llvm-project`, run `llvm.yml` with
   `llvm_ref=<branch>` and a new `version`, then pass that `llvm_release` to `graalvm.yml`.
3. The Native Image LLVM backend is registered by `substratevm/mx.substratevm/mx_substratevm.py`
   (`llvm_supported`, GR-34811). Windows has no backend code path yet; when a branch adds it,
   drop the Windows exclusion there and the smoke test picks the backend up automatically
   (it checks for `lib/svm/tools/llvm-backend`).

## Platform status (2026-09-17)

| Platform | LLVM toolchain | Sulong (`lli`) | Native Image LLVM backend |
|----------|----------------|----------------|---------------------------|
| linux-amd64 | yes | yes | yes, smoke-tested (`--tool:llvm-backend`) |
| windows-amd64 | yes | yes | no: the backend has no Windows code path (unwinding, partial link, objcopy) |
| darwin-aarch64 | yes | yes | no: blocked by GR-34811 |

The `graal/25.3.4.1-ci` branch registers the backend on darwin-aarch64, but the image
builder then aborts with "Unexpected image builder module-dependencies": in
`substratevm/mx.substratevm/suite.py` the darwin/aarch64 entries of
`LLVM_PLATFORM_SPECIFIC_SHADOWED` and `JAVACPP_PLATFORM_SPECIFIC_SHADOWED` are the only
ones without a `moduleName`, so those JavaCPP jars load as automatic modules. Making the
macOS backend work needs modular (module-info) builds of those two jars for macosx-arm64.
Releases are therefore built from the pristine `graal-25.3.4.1` tag.

The backend's tool macro sets the experimental `-H:CompilerBackend=llvm` option, so use
`native-image -H:+UnlockExperimentalVMOptions --tool:llvm-backend ...` (or leave
`NATIVE_IMAGE_EXPERIMENTAL_OPTIONS_ARE_FATAL` unset).

## Local checks

    python3 -m pytest tests -q
    bash tests/test_package_llvm.sh && bash tests/test_package_graalvm.sh
