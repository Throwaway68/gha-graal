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

**LLVM toolchain** (`llvm.yml`): `gh workflow run llvm.yml -f llvm_ref=graal/22.1.8-win -f version=22.1.8-graal.3`.
Those two values are the workflow's defaults, i.e. the release the branch currently needs, so a run
without inputs stops at the "already exists and is published" guard; bump `version` for a new release.
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

**GraalVM** (`graalvm.yml`): `gh workflow run graalvm.yml -f graal_ref=graal/25.3.4.1-win-llvm -f llvm_release=llvm-22.1.8-graal.3 -f label=round1-win-llvm -f platforms=linux-amd64,windows-amd64`
(the first two are also the defaults; `platforms` must exclude darwin-aarch64 for now, see the
platform status below). Builds any graal ref against the LLVM release: graal's
downloads from `lafo.ssw.uni-linz.ac.at/pub/llvm` are redirected with `MX_URLREWRITES`
(pattern + digest override), so no suite file is edited. Every platform runs
`scripts/graalvm/smoke.sh` (java, native-image, `lli`, a C hello world through the bundled
toolchain, and a Java hello world with `--tool:llvm-backend` wherever the GraalVM carries
`lib/svm/tools/llvm-backend`) before it packages. Publishes release `graalvm-<label>` with a
`.tar.gz` per Unix platform, a `.zip` for Windows, and `manifest.json`, as a draft whose ~1 GB
assets are uploaded one by one with retries and verified before the draft flag is cleared -
the same hardening as `llvm.yml`, and for the same HTTP 500s.

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
`jars-<version>` with the two jars and `manifest.json` (sha512). The relocation itself is
`scripts/jars/shadow.py`. Nothing consumes the release today: `graal/25.3.4.1-win-llvm` took the
stock `org.bytedeco` jars instead, so `jars-1.5.7-graal.1` stays published only as a record.

**Windows EH spike** (`spike-win-eh.yml`): `gh workflow run spike-win-eh.yml -f llvm_release=llvm-22.1.8-graal.3`.
A standalone windows-2022 check of the assumptions the Windows backend rests on, from
`tests/spike/win-eh/`: `llc` emits a Win64 `.xdata` LSDA for a custom personality, libunwind
builds in SEH mode with the bundled clang, an MSVC-linked program unwinds through it, and the
toolchain binaries start without an `.exe` suffix. No release and nothing depends on it; it is
the evidence behind the design decisions recorded in the journal.

## Building your own branches

1. Push a branch to `Throwaway68/graal` (any base). Run `graalvm.yml` with `graal_ref=<branch>`.
   Forks do not carry upstream tags: to build an upstream tag, push it to the fork first
   (`git push <fork> refs/tags/<tag>:refs/tags/<tag>`); `graal-25.3.4.1` is already pushed.
2. To change LLVM, push a branch to `Throwaway68/llvm-project`, run `llvm.yml` with
   `llvm_ref=<branch>` and a new `version`, then pass that `llvm_release` to `graalvm.yml`.
3. The Native Image LLVM backend is registered by `substratevm/mx.substratevm/mx_substratevm.py`
   (`llvm_supported`). The smoke test picks it up automatically wherever the built GraalVM has
   `lib/svm/tools/llvm-backend`.
4. Branch plumbing: `graal/25.3.4.1-win-llvm` is the Windows backend branch and the default of
   `graalvm.yml` and `graalvm-dev.yml`. It requires LLVM release `llvm-22.1.8-graal.3` or newer
   (Win64 home space for `CallingConv::GRAAL` plus the Windows libunwind); with
   `llvm-22.1.8-graal.2` the image still links, but a JNI entry point with more than four
   arguments reads argument five 32 bytes low and the image faults. For JavaCPP and LLVM it uses
   the **stock `org.bytedeco` jars from Maven Central on every platform**, not Oracle's shadowed
   ones, so release `jars-1.5.7-graal.1` is *not* a dependency of this branch - it is a retained
   record of what was tried in task 4 and nothing references it (see the journal's Decisions).
   `graal/25.3.4.1-ci` stays as it was, for comparing against the darwin-only change.

## Platform status (2026-09-17)

| Platform | LLVM toolchain | Sulong (`lli`) | Native Image LLVM backend |
|----------|----------------|----------------|---------------------------|
| linux-amd64 | yes | yes | yes, smoke-tested (`--tool:llvm-backend`) |
| windows-amd64 | yes | yes | yes (round 1: hello world), smoke-tested on `graal/25.3.4.1-win-llvm` |
| darwin-aarch64 | yes | yes | no: `llc` rejects the aarch64 batches |

Round 1 on windows-amd64 means exactly what the smoke test shows: `native-image
--tool:llvm-backend` builds a Java hello world and the image prints and exits 0. Exceptions unwind
through libunwind in SEH mode, but nothing beyond a hello world has been run; see the journal for
what each piece does. The build is published as
[`graalvm-round1-win-llvm`](https://github.com/Throwaway68/gha-graal/releases/tag/graalvm-round1-win-llvm)
(`graal/25.3.4.1-win-llvm` at `fea81ecaff4` against `llvm-22.1.8-graal.3`).

On darwin-aarch64 the branch registers the backend as well - the module problem of
`graal/25.3.4.1-ci` is gone, because this branch uses the stock `org.bytedeco` jars on every
platform - but the smoke test still fails in the backend: `llc` refuses
`llvm.read_register`/`llvm.write_register` on `x27` and `x28` (heap base and thread pointer), so
no aarch64 batch compiles. That is open for round 2 and the reason release
`graalvm-round1-win-llvm` carries linux-amd64 and windows-amd64 only. Until it is fixed, a release
build has to be started with `-f platforms=linux-amd64,windows-amd64`: the release job needs every
matrix job, so one failing darwin job means no release at all.

The backend's tool macro sets the experimental `-H:CompilerBackend=llvm` option, so use
`native-image -H:+UnlockExperimentalVMOptions --tool:llvm-backend ...` (or leave
`NATIVE_IMAGE_EXPERIMENTAL_OPTIONS_ARE_FATAL` unset).

## Local checks

    python3 -m pytest tests -q
    bash tests/test_package_llvm.sh && bash tests/test_package_graalvm.sh
