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
| `Throwaway68/graal` | `graal/25.3.4.1-win-llvm` | graal-25.3.4.1 + the Native Image LLVM backend on windows-amd64 and darwin-aarch64 (see the journal) |

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

**GraalVM** (`graalvm.yml`): `gh workflow run graalvm.yml -f graal_ref=graal/25.3.4.1-win-llvm -f llvm_release=llvm-22.1.8-graal.3 -f label=round2-win-llvm -f platforms=linux-amd64,windows-amd64`
(the first two are also the defaults; `platforms` has excluded darwin-aarch64 up to and including
the round 2 release - the backend works there since 2026-09-18 but no release has been built with it
yet, see the platform status below). Builds any graal ref against the LLVM release: graal's
downloads from `lafo.ssw.uni-linz.ac.at/pub/llvm` are redirected with `MX_URLREWRITES`
(pattern + digest override), so no suite file is edited. Every platform runs
`scripts/graalvm/smoke.sh` (java, native-image, `lli`, a C hello world through the bundled
toolchain, and a Java hello world with `--tool:llvm-backend` wherever the GraalVM carries
`lib/svm/tools/llvm-backend`) and then, where the backend is there,
`scripts/graalvm/smoke-stress.sh` (`tests/programs/stress` through `dev-run.sh`: exceptions, GC and
threads) before it packages. Publishes release `graalvm-<label>` with a
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

**Program directories.** `tests/programs/<program>` is the contract `scripts/graalvm/dev-run.sh`
implements, and it is the same one `scripts/graalvm/smoke-stress.sh` and the release smoke tests
use. Required: the `*.java` sources, whose main class is the directory name capitalised (`hello` ->
`Hello`), and `expected.txt`, every line of which must appear in the image's stdout. Optional, each
one picked up by its mere presence:

- `javac.flags` - one line of extra `javac` arguments, word-split (`complex` uses
  `--add-modules org.graalvm.nativeimage`).
- `META-INF/` - copied into the classpath, so `native-image` finds
  `META-INF/native-image/<group>/<artifact>/jni-config.json` and `native-image.properties` by
  itself and the program needs no arguments on the command line.
- `*.c` - compiled by the **bundled** clang (`$GRAALVM_HOME/lib/llvm/bin/clang`), against the JNI
  headers of the GraalVM under test, into one shared library named after the program
  (`<work>/complex.dll`, `<work>/libcomplex.dylib`, `<work>/libcomplex.so`). The image is then run
  with `-D<program>.lib=<absolute path>`, which is how `tests/programs/complex` knows what to
  `System.load`.

**Interactive session on the Windows runner.** `-f debug_ssh=true` stops the dev job after `dev-run`
and opens a shell on the runner: tmate on linux/macOS, and on windows-amd64 the Windows OpenSSH
server behind a cloudflared quick tunnel (`scripts/graalvm/win-ssh.ps1`), because tmate's action
hangs on windows-2022.

    gh workflow run graalvm-dev.yml -f platform=windows-amd64 -f program=hello -f debug_ssh=true
    gh run download <run-id> -n ssh-windows-amd64     # ~10 min after the dispatch, once the build is through
    ssh -i ~/.ssh/<your key> -o ProxyCommand="cloudflared access tcp --hostname %h" \
        -o StrictHostKeyChecking=no runneradmin@<the hostname from address.txt>

The artifact is `ssh-<platform>` on Windows and `tmate-<platform>` on linux/macOS (the log cannot be
read through the API while the job runs, so the address travels as an artifact). Its `address.txt`
holds the trycloudflare hostname, that exact ssh command, and the hold file. Only the public keys of
the GitHub account that dispatched the run are authorized, so that account needs one at
https://github.com/settings/keys and you need the matching private key; the local end needs
`cloudflared` (`brew install cloudflared`). The shell is Git bash, starts in `$GITHUB_WORKSPACE` and
carries the job's environment - `cl`, `link`, `$GRAALVM_HOME`, `$JAVA_HOME`, `$MX_PATH/mx` - for
interactive logins and for `ssh <host> '<command>'` alike, so another build of the same program is

    bash ci/scripts/graalvm/dev-run.sh "$GRAALVM_HOME" ci/tests/programs/hello "$GITHUB_WORKSPACE/work2"

The job waits in its hold step until you end the session with `rm "$RUNNER_TEMP/gha-hold"`, then
finishes normally and still uploads `dev-<platform>-<program>`; unattended it holds for 180 minutes
at most. If `cloudflared` answers `lookup ... no such host`, your resolver filters
`*.trycloudflare.com` - some ISP resolvers do; one way out without touching the system resolver is to
run the client in a container: `-o ProxyCommand="docker run -i --rm --dns 8.8.8.8
cloudflare/cloudflared access tcp --hostname %h"`.

The tmate side is not reliable on macos-14: in run 35345568476 the `mxschmitt/action-tmate` step sat
there for 25 minutes without ever publishing an address and the run had to be cancelled. When a
darwin failure is in a toolchain invocation rather than in the builder there is a faster route than
a session anyway - download that platform's LLVM release asset and the `dev-<platform>-<program>`
artifact of the failed run (it carries `work/tmp/**/llvm/*.o`, the real batch objects) and reproduce
the step locally. That is how three of the four darwin fixes were found; see the journal.

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

## Platform status (2026-09-18)

| Platform | LLVM toolchain | Sulong (`lli`) | Native Image LLVM backend |
|----------|----------------|----------------|---------------------------|
| linux-amd64 | yes | yes | yes (round 2: exceptions, GC, threads), smoke-tested (`--tool:llvm-backend`) |
| windows-amd64 | yes | yes | yes (round 2: exceptions, GC, threads), smoke-tested on `graal/25.3.4.1-win-llvm` |
| darwin-aarch64 | yes | yes | yes (round 2: exceptions, GC, threads) on `graal/25.3.4.1-win-llvm`; `graalvm.yml`'s own smoke test has not been run there yet |

Releases of the Windows backend branch, newest first:

- [`graalvm-round2-win-llvm`](https://github.com/Throwaway68/gha-graal/releases/tag/graalvm-round2-win-llvm):
  `graal/25.3.4.1-win-llvm` at `4def28820c5` against `llvm-22.1.8-graal.3`, linux-amd64 and
  windows-amd64. Round 2 means the release's own smoke test builds and runs `tests/programs/stress`
  with `--tool:llvm-backend` on both platforms, not just a hello world: a throw caught 60 frames up
  whose stack trace must still show 60 frames, six kinds of implicit exception (NPE, array index,
  division, class cast, array store, negative array size), rethrow-and-wrap through a lambda,
  `finally` ordering, garbage collections taken through live frames, a weak reference that must be
  cleared and enqueued, 1 GiB of allocation pressure with a checked survivor set, threads
  (start/join, `synchronized`, `wait`/`notify`, collections taken while four workers recurse and eight more allocate) and an
  uncaught exception on a second thread. Eleven `OK <check>` lines and `STRESS OK`; see the journal
  for what each Windows-specific piece does.
- [`graalvm-round1-win-llvm`](https://github.com/Throwaway68/gha-graal/releases/tag/graalvm-round1-win-llvm):
  `graal/25.3.4.1-win-llvm` at `fea81ecaff4` against `llvm-22.1.8-graal.3`. Round 1 meant exactly
  what its smoke test showed: `native-image --tool:llvm-backend` builds a Java hello world and the
  image prints and exits 0. Exceptions unwound through libunwind in SEH mode, but nothing beyond a
  hello world had been run.

What `stress` does **not** cover, and is therefore still open: `tests/programs/overflow` (a
`StackOverflowError` caught after recursion) fails on windows-amd64 *and* on linux-amd64, so it is a
backend bug rather than a Windows one; a caught exception inside an allocating eight-thread loop
crashed the linux-amd64 image with stale references after the catch (run 35325689605) and was taken
out of `stress`, and `tests/programs/excgc`, written to reproduce it single-threaded, passes on both
platforms, so that crash is unreproduced and unexplained; a throw across an MSVC-compiled frame is
untested (round 4); and the substratevm LLVM gate has not been run on this branch (round 3). The
journal has the detail for each.

JNI in both directions is covered by `tests/programs/complex` as of 2026-09-18 and is green on
linux-amd64 (run https://github.com/Throwaway68/gha-graal/actions/runs/35355533926) and on
darwin-aarch64 (run https://github.com/Throwaway68/gha-graal/actions/runs/35356407402): downcalls
into a shared library the *bundled* clang builds on the runner, upcalls into the image including
one whose Java side throws, a `ThrowNew` from C caught in Java, a `@CEntryPoint` entered from C
through a function pointer, and the same traffic from six threads at once. windows-amd64 is round
4's open platform.

On darwin-aarch64 the backend works as of 2026-09-18: `hello` prints
`Hello from the LLVM backend on Mac OS X` and `DEV-RUN OK`
(run https://github.com/Throwaway68/gha-graal/actions/runs/35347138049), and `stress` - the same
eleven checks that define round 2 on the other two platforms - is green there on the first try
(run https://github.com/Throwaway68/gha-graal/actions/runs/35347790516), with no darwin-specific
work on exceptions, GC or threads. It took four fixes, all in
`substratevm/src/com.oracle.svm.core.graal.llvm/`, one graal commit each:

- `bc99e7129b9` - `llc` refused `llvm.read_register`/`llvm.write_register` on `x27` and `x28` (heap
  base and thread pointer) because nothing reserved them, so no aarch64 batch compiled;
  `-mattr=+reserve-x27,+reserve-x28`. Not darwin-specific - linux-aarch64 would hit it too.
- `a6914a70208` - `ld64.lld` does not implement `-r`, so the relocatable link of the compiled
  batches runs the platform linker (`ld -r`) instead.
- `ac778fbcab5` - `llvm-objcopy --add-symbol` is ELF only, so `__svm_code_section` and
  `__svm_text_end` come from two marker objects that bracket the batches in the input order of that
  link, checked against the linked object afterwards.
- `6dfc22e0897` - `llvm-objcopy --remove-section` needs the canonical
  `__LLVM_STACKMAPS,__llvm_stackmaps` on Mach-O; with the bare section name it removes nothing and
  still exits 0, and 4.8 MB of stack maps went into every image.

All four are toolchain-invocation fixes, not code generation. Releases `graalvm-round1-win-llvm`
and `graalvm-round2-win-llvm` still carry linux-amd64 and windows-amd64 only, because they were
built before this, and `tests/programs/overflow` (which fails on the other two platforms) has not
been tried on darwin. The journal has a Finding per fix.

The backend's tool macro sets the experimental `-H:CompilerBackend=llvm` option, so use
`native-image -H:+UnlockExperimentalVMOptions --tool:llvm-backend ...` (or leave
`NATIVE_IMAGE_EXPERIMENTAL_OPTIONS_ARE_FATAL` unset).

## Local checks

    python3 -m pytest tests -q
    bash tests/test_package_llvm.sh && bash tests/test_package_graalvm.sh
