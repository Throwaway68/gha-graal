# Windows LLVM backend journal

Working notes for porting the Native Image LLVM backend to windows-x86_64.
Spec: docs/superpowers/specs/2026-09-17-windows-llvm-backend-design.md.
Every entry is dated (YYYY-MM-DD) and names the commit or workflow run it comes from.

## Milestones

- 2026-09-17: Windows exception-handling spike green on windows-2022 (steps 1-4 of the plan's Task 2):
  https://github.com/Throwaway68/gha-graal/actions/runs/35207963198, re-run green after the review fixes
  (hard step-1 assertions, strict COFF rewriter):
  https://github.com/Throwaway68/gha-graal/actions/runs/35209025076
- 2026-09-17: LLVM release `llvm-22.1.8-graal.2` with Windows libunwind, all three platforms green
  (run https://github.com/Throwaway68/gha-graal/actions/runs/35212270484; the tag was rebuilt from
  run 35209720023 after the review fix below). Seven assets as in graal.1;
  `llvm-22.1.8-graal.2-windows-amd64.tar.gz` carries `lib/x86_64-w64-windows-gnu/libunwind.a`, the same
  archive as `unwind.lib`, and `include/unwind.h`, and nothing loose at its root. ~~This is the release
  tasks 5 to 9 consume.~~ **Superseded - see the milestone for LLVM release `llvm-22.1.8-graal.3`
  below: tasks 5 to 7 consumed graal.2, but tasks 8 and 9 and the round-1 release consume
  `llvm-22.1.8-graal.3`, which adds the Win64 home-space fix.**

- 2026-09-17: ~~Shadowed jars release `jars-1.5.7-graal.1`
  (run https://github.com/Throwaway68/gha-graal/actions/runs/35215356056, green first try):
  `javacpp-shadowed-1.5.7-graal.1-windows-x86_64.jar`,
  `llvm-shadowed-13.0.1-1.5.7-graal.1-windows-x86_64.jar` and `manifest.json`, built by
  `.github/workflows/jars.yml` from the Maven Central windows-x86_64 platform jars with
  `scripts/jars/shadow.py`. Task 6 points suite.py's windows-amd64
  `JAVACPP_PLATFORM_SPECIFIC_SHADOWED` / `LLVM_PLATFORM_SPECIFIC_SHADOWED` at them.~~
  **Superseded - see the stock-jars decision (2026-09-17, controller ruling, task 6) in Decisions
  below. suite.py points every platform at the stock `org.bytedeco` Maven Central jars, so nothing
  references `jars-1.5.7-graal.1`; the release, `jars.yml` and `shadow.py` stay as the record of what
  was tried.**

- 2026-09-17: Dev loop ready, validated on the pristine tag `graal-25.3.4.1`
  (`.github/workflows/graalvm-dev.yml` + `mx-env/ce-llvm-dev`, final shape in commit e93fe15):
  linux-amd64 green with `DEV-RUN OK`
  (https://github.com/Throwaway68/gha-graal/actions/runs/35232601109, 7m50s), windows-amd64 builds
  and fails only at `dev-run`
  (https://github.com/Throwaway68/gha-graal/actions/runs/35232589440, download cache miss, 9m02s;
  https://github.com/Throwaway68/gha-graal/actions/runs/35233656718, hit, 9m43s). Tasks 6 to 8
  iterate with
  `gh workflow run graalvm-dev.yml -R Throwaway68/gha-graal -f graal_ref=<ref>
  -f llvm_release=llvm-22.1.8-graal.2 -f platform=<p> -f program=<dir> -f ni_args='<args>'`; the
  `dev-<platform>-<program>` artifact carries `work/stdout.txt`, `work/stderr.txt`, the
  native-image reports and the LLVM objects of the run.

- 2026-09-17: **Windows enters the LLVM pipeline** (graal commits 9aad563fd45 and 6962b05ef22 on
  `graal/25.3.4.1-win-llvm`, run https://github.com/Throwaway68/gha-graal/actions/runs/35236412885).
  `svml` is registered on windows-amd64, `mx build` succeeds against the windows-x86_64 shadowed
  jars, the module gate passes, and `native-image --tool:llvm-backend` gets through analysis and
  into `SubstrateLLVMBackend.emitLLVM` -> `LLVMGenerator.<init>` -> `LLVMIRBuilder.<init>` in
  [6/8] Compiling methods. It does not get out of that constructor yet - see the finding below on
  the shadowed native libraries. The branch is neutral on linux-amd64: `DEV-RUN OK` both at
  9aad563fd45 (https://github.com/Throwaway68/gha-graal/actions/runs/35236400414, 7m44s) and at the
  branch head (https://github.com/Throwaway68/gha-graal/actions/runs/35239817876), so the
  header-free unwind declarations are a no-op where the header exists.

- 2026-09-17: **Windows reaches the LLVM link stage** (graal commit ae2a36f7040, run
  https://github.com/Throwaway68/gha-graal/actions/runs/35242773448). With the stock
  `org.bytedeco` jars, `native-image --tool:llvm-backend` on windows-amd64 runs the whole pipeline
  - `[6/8] Compiling methods` (16.8s), `[7/8] Laying out methods` (20.1s) - and fails exactly where
  the plan expects Task 7 to take over:

  ```
  jdk.graal.compiler.debug.GraalError: Native linking failed into the final object file (D:\a\gha-graal\gha-graal\work\tmp\SVM-1789660848999\llvm\llvm.o): 1
      at ...LLVMToolchainUtils.nativeLink(LLVMToolchainUtils.java:140)
      at ...LLVMNativeImageCodeCache.linkCompiledBatches(LLVMNativeImageCodeCache.java:205)
  ```

  The run artifact holds the six inputs of that link, `b0.o`..`b5.o`, and they are real x86-64
  COFF: `file b0.o` says "Intel amd64 COFF object file, not stripped, 33 sections, 5197 symbols".
  So `llc` consumes the `x86_64-pc-windows-msvc` bitcode the backend emits and produces usable
  objects; what is left is `lld-link -r -o llvm.o b0.o ...`, and `-r` is a GNU-ld flag that the
  MSVC-style `lld-link` driver does not have (`LLVMObjectFile.getLld()` maps PECOFF to
  `lld-link`). Note for task 7: `nativeLink` swallows the linker's own message into
  `debug.log("%s", e.getOutput())`, so the console shows only the exit status. linux-amd64 is
  `DEV-RUN OK` on the same commit
  (https://github.com/Throwaway68/gha-graal/actions/runs/35242758887, 7m43s).

- 2026-09-17: **Windows produces a single COFF object and reaches the final link** (graal commits
  6b409222e7c, e7ed89f0bb9 and 2c64a5498c2 on `graal/25.3.4.1-win-llvm`, run
  https://github.com/Throwaway68/gha-graal/actions/runs/35248532685). All 5,249 methods of the
  `hello` program go into one LLVM batch, `llc` turns it into `b0.o`, which is copied to `llvm.obj`
  (there is no `ld -r` on PE/COFF); `parseCode` finds `.text$svm1` and every method offset in it,
  `llvm-objcopy` strips the 4.8 MB stack map section, the image object is written and `cl.exe` runs
  the real link. It fails exactly where task 8 picks up:

  ```
  app.obj : error LNK2001: unresolved external symbol _Unwind_RaiseException
  llvm.obj : error LNK2001: unresolved external symbol _Unwind_RaiseException
  D:\a\gha-graal\gha-graal\work\app.exe : fatal error LNK1120: 5 unresolved externals
  ```

  (the five are `_Unwind_RaiseException`, `_Unwind_GetIPInfo`, `_Unwind_GetLanguageSpecificData`,
  `_Unwind_GetRegionStart`, `_Unwind_SetIP`; there is no unresolved `__svm_seh_personality`,
  because the personality is the Java method `LLVMExceptionUnwind.personality` and its
  `IsolateEnterStub` is compiled into `llvm.obj` like any other method). linux-amd64 is `DEV-RUN OK`
  on the same branch head (https://github.com/Throwaway68/gha-graal/actions/runs/35248894118) and
  on the first of the three commits
  (https://github.com/Throwaway68/gha-graal/actions/runs/35245906387).

- 2026-09-17: **Hello world runs on windows-amd64 with the LLVM backend** (graal commit
  `c397f423961` on `graal/25.3.4.1-win-llvm`, LLVM release `llvm-22.1.8-graal.3`, dev run
  https://github.com/Throwaway68/gha-graal/actions/runs/35285287516):

  ```
  == run
  Hello from the LLVM backend on Windows Server 2022
  args=0
  DEV-RUN OK
  ```

  `native-image --tool:llvm-backend` generates `app.exe` (7.14 MiB, PE32+ x64, Windows CUI) in
  1m09s, the image starts, `System.out.println` goes through the JNI function table and back into
  Java, and the process exits 0. That is the whole chain the last five tasks built: the backend is
  registered on Windows (task 6), all 5,249 methods go into one COFF object whose `.text$svm1`
  gives the code range (task 7), and every function names `__svm_seh_personality`, which forwards
  to libunwind's `_GCC_specific_handler` linked out of the toolchain bundle (task 8). linux-amd64
  is `DEV-RUN OK` on the same commit and release
  (https://github.com/Throwaway68/gha-graal/actions/runs/35284148467, `Hello from the LLVM backend
  on Linux`). Both platforms are green again at the branch head `fea81ecaff4`
  (windows https://github.com/Throwaway68/gha-graal/actions/runs/35286082187, linux
  https://github.com/Throwaway68/gha-graal/actions/runs/35286084181).

- 2026-09-17: LLVM release `llvm-22.1.8-graal.3`
  (https://github.com/Throwaway68/gha-graal/releases/tag/llvm-22.1.8-graal.3, run
  https://github.com/Throwaway68/gha-graal/actions/runs/35282186301), built from
  `Throwaway68/llvm-project@graal/22.1.8-win` (commit `9d497c85ebdb`, the one-`case` Win64 home
  space fix). Seven assets, the same set as graal.2, including the Windows libunwind.
  `llvm-22.1.8-graal.2` is untouched. This is the release the branch consumes from now on and the
  default of `graalvm-dev.yml`.

- 2026-09-17: **Round 1 release `graalvm-round1-win-llvm`**
  (https://github.com/Throwaway68/gha-graal/releases/tag/graalvm-round1-win-llvm, run
  https://github.com/Throwaway68/gha-graal/actions/runs/35290879456), built by `graalvm.yml` from
  `graal/25.3.4.1-win-llvm` (head `fea81ecaff4`) against `llvm-22.1.8-graal.3`, with the full
  `ce-llvm-ci` GraalVM (CE base, LLVM.org toolchain, Sulong, toolchain launchers, LLVM backend).
  Three assets: `graalvm-round1-win-llvm-linux-amd64.tar.gz` (1,166,396,214 B),
  `graalvm-round1-win-llvm-windows-amd64.zip` (1,675,262,796 B), `manifest.json` (sha512 of both).
  Per-platform smoke (`scripts/graalvm/smoke.sh`: java, native-image, `lli`, a C hello world
  through the bundled toolchain, then `native-image --tool:llvm-backend`):

  - **windows-amd64 green** (job 36m10s, the image builds in 1m28s to
    `D:\a\gha-graal\gha-graal\smoke\hello-llvm.exe (executable, 7.14MiB)`):

    ```
    == Native Image LLVM backend
    ...
    Finished generating 'hello-llvm' in 1m 28s.
    Hello from the LLVM backend
    LLVM backend: tested
    SMOKE OK
    ```

  - **linux-amd64 green** (job 29m18s): same `Hello from the LLVM backend` / `LLVM backend: tested`
    / `SMOKE OK`.
  - **darwin-aarch64 is not in this release.** The first attempt with all three platforms
    (run https://github.com/Throwaway68/gha-graal/actions/runs/35288617506) had windows-amd64
    (36m06s) and linux-amd64 (29m) green with exactly those lines, and darwin-aarch64 failing in
    the smoke test's backend step (finding below); one failed matrix job skips the release job, so
    the release was rebuilt with `platforms=linux-amd64,windows-amd64`.

  The release job took 1m46s with the task-8 hardening ported from `llvm.yml`: draft release, each
  asset uploaded on its own (all three succeeded on attempt 1/6), verified by published size and
  `state == uploaded`, then `gh release edit --draft=false`.

- 2026-09-18: **interactive ssh on windows-2022 works** (round 2, task 1). `debug_ssh: true` now
  opens a real session on the Windows runner - the Windows OpenSSH server behind a cloudflared quick
  tunnel, `scripts/graalvm/win-ssh.ps1` - instead of the warning that said there is none.
  End-to-end run https://github.com/Throwaway68/gha-graal/actions/runs/35325615444 (windows-amd64,
  `hello`, `debug_ssh=true`, green): job start 08:41:01Z, build 8m22s, `dev-run` 1m36s, the ssh step
  50 s, artifact `ssh-windows-amd64` uploaded at 08:53:19Z - **12m18s from dispatch to a usable
  shell**, of which the session setup is under a minute; the rest is the build the session is there
  to debug. In that session, from the Mac:

  ```
  $ ssh -i <key> -o ProxyCommand="cloudflared access tcp --hostname %h" runneradmin@<host> \
      'cd "$GITHUB_WORKSPACE" && "$GRAALVM_HOME/bin/native-image.cmd" --version && cl 2>&1 | head -1 \
       && ls work && bash ci/scripts/graalvm/dev-run.sh "$GRAALVM_HOME" ci/tests/programs/hello "$GITHUB_WORKSPACE/work2"'
  native-image 25.0.4.1 2026-08-18
  GraalVM Runtime Environment GraalVM CE 25.3.4.1-dev+1.1 (build 25.0.4.1+1-jvmci-25.3-b22)
  Substrate VM GraalVM CE 25.3.4.1-dev+1.1 (build 25.0.4.1+1, serial gc, compressed references)
  Microsoft (R) C/C++ Optimizing Compiler Version 19.44.35228 for x64
  app.exe classes stderr.txt stdout.lf stdout.txt tmp
  ...
  Finished generating 'app' in 1m 28s.
  Hello from the LLVM backend on Windows Server 2022
  DEV-RUN OK
  ```

  The second `dev-run` took 1m37s of wall time end to end, against 1m36s for the job's own `dev-run`
  step - an iteration inside the session costs what the step costs, and saves the 8m22s build. `rm
  "$RUNNER_TEMP/gha-hold"` ended the hold (08:56:36Z) and the job finished green and still uploaded
  `dev-windows-amd64-hello`. The mechanism was spiked green on the first attempt in run
  https://github.com/Throwaway68/gha-graal/actions/runs/35325048211 (the throwaway spike workflow is
  deleted again); what it takes is in Findings below.

## Findings

- 2026-09-17 (runs https://github.com/Throwaway68/gha-graal/actions/runs/35232589440,
  https://github.com/Throwaway68/gha-graal/actions/runs/35233656718 and
  https://github.com/Throwaway68/gha-graal/actions/runs/35232601109): **the workflow after the
  ruling - one download cache, no build cache - measured on `graal-25.3.4.1`.**

  | run | platform | mx download cache | build | dev-run | total |
  |-----|----------|-------------------|-------|---------|-------|
  | 35232589440 | windows-amd64 | miss, saved in 46 s | 7m12s | fails at `--tool:llvm-backend` | 9m02s |
  | 35233656718 | windows-amd64 | hit (1236 MB, restored in 15 s), not saved again | 8m05s | same failure | 9m43s |
  | 35232601109 | linux-amd64 | miss, saved in 15 s | 5m42s | `DEV-RUN OK` | 7m50s |

  The cache does what it is there for: `Downloading LLVM_ORG [duration: 49.14]` and 64 download
  lines on the miss become `[duration: 0.0008]` and 32 lines on the hit, about 60 to 70 s of the
  build step. It does not show in the totals because a windows-2022 build of this GraalVM varies by
  ±2 min between runners (5m50s to 8m14s measured for identical input), which is worth remembering
  when reading any single Windows timing in this journal. The key is per platform because
  `hashFiles` sees different `suite.py` content on Windows (line endings), which is harmless.


- 2026-09-17 (runs https://github.com/Throwaway68/gha-graal/actions/runs/35224907245 and
  https://github.com/Throwaway68/gha-graal/actions/runs/35224918546): **the pristine tag's Windows
  GraalVM has no `--tool:llvm-backend` macro, and that is exactly how the dev workflow fails.**
  `dev-run` dies after 4 s with
  ```
  == native-image (LLVM backend)
  Error: Unknown name in option specification: tool:llvm-backend
  ```
  (exit code 20), because `substratevm/mx.substratevm/mx_substratevm.py` registers the backend
  component only where `llvm_supported = not (mx.is_windows() or (mx.is_darwin() and
  mx.get_arch() == "aarch64"))` holds, so `lib/svm/tools/llvm-backend` does not exist. Everything
  before it - build, cache save, artifact upload - succeeds. Task 6 turns this message into a
  real backend run.

- 2026-09-17 (same runs): **an unknown component short name is only a warning, so one env file
  serves every platform.** `svml` in `mx-env/ce-llvm-dev`'s COMPONENTS prints
  `WARNING: The component inclusion list ('--components' or '$COMPONENTS') includes an unknown
  component: 'svml'` on Windows (`sdk/mx.sdk/mx_sdk_vm_impl.py`, `_components_include_list`) and
  the build continues. The final list is `cmp,svm,ni,nil,sdkni,svml,llp`; mx expands dependencies
  transitively, so `mx graalvm-show` reports Graal SDK Compiler (sdkc), Graal SDK Native Image
  (sdkni), GraalVM compiler (cmp), LLVM.org toolchain (llp), Native Image (ni), Native Image LLVM
  Backend (svml, linux only), Native Image licence files (nil), SubstrateVM (svm), SubstrateVM
  Static Libraries (svmsl), Truffle Compiler (tflc) and Truffle Runtime SVM (svmt). Launchers:
  `native-image` native, both agent libraries skipped. No component dependency had to be added.

- 2026-09-17 (runs 35216649197, 35217642476, 35219010453, 35221772232, 35226210569, 35227444918,
  35229643502, 35230528428): **`graalvm-dev.yml` caches mx's downloads and nothing else; a cache of
  the build outputs does not pay for this loop.** mx rebuilds a target when an input is newer than
  its output (`JavaBuildTask._compute_build_reason`, `TimeStampFile.isOlderThan`), and a hosted run
  hands it fresh inputs in five independent ways, each of which by itself rebuilds the whole
  GraalVM out of a fully populated `mxbuild`:
  1. `actions/checkout` stamps every source with the time of the run while the cache restores
     `mxbuild` with the mtimes of the run that built it: `HostProxyException.class[11:38:28] is
     older than HostProxyException.java[11:49:01]`.
  2. mx re-downloads its dependencies into `~/.mx/cache`, and a fresh download outranks every
     output: `dependency LLVM_ORG updated` re-archives the 1.5 GB LLVM toolchain (106 s) and both
     GraalVM layouts, `dependency ANTLR4/XZ/JSON/ICU4J updated` re-shades the jars and recompiles
     the Truffle processors and everything behind them.
  3. mx deletes and re-downloads the LabsJDK (`Deleting stale ...jdk-dl...`) and records the
     timestamp of its `lib/modules` in the graalvm-jimage config, so `the configuration changed`
     rebuilds the jimage, both layouts and `native-image.exe`.
  4. Directories count as inputs (`llvm-toolchain.tar[12:22:14] is older than
     graal\sdk\llvm-patches\backports`; ninja's generator rule watches each native project's
     `include`), and **on NTFS a directory cannot be kept old**: file timestamps are duplicated
     into the parent's index entry and flushed asynchronously, so a directory that verified as
     2000-01-01 at 13:21:16.8 read as 13:21:18.4 to ninja 1.6 s later.
  5. ninja's deps log stores the mtime each object had when its headers were recorded, so making
     the objects newer means `stored deps info out of date for 'src/launcher.obj'`.
  All five can be beaten - backdate the checkouts and the JDK, put the restored `mxbuild` an hour
  ahead except for ninja's objects and the sources mx generates for them - and the payoff is real
  when the *same* graal commit is rebuilt: windows-amd64 7m32s -> 0m21s of build (total 12m26s ->
  5m22s, restoring 5 GB costs 2m38s), linux-amd64 5m38s -> 0m36s (9m35s -> 4m33s). But that is the
  wrong case for this loop: tasks 6 to 8 push a new graal commit per iteration, and a cache from a
  *different* commit reuses nothing at all (every source has the time of the run), so it only adds
  ~2 min to restore and ~3.5 min to save on Windows - the first cached Windows run was slower than
  the cold one, 7m18s vs 6m00s of build. Worse, the key named only platform + JDK + graal SHA: the
  same graal commit rebuilt against a **new `llvm_release`** would have restored the old toolchain,
  and the future-stamping would have kept it. Hence the ruling below. What remains is the download
  cache, ~1.2 to 1.5 GB per platform, keyed by platform + `llvm_release` + a hash of
  `common.json` and the `suite.py` files, which is what actually decides those downloads, with one
  fallback so that editing suite.py (task 6) does not re-download everything. `jdk-dl` is not
  cached: mx deletes and re-downloads the LabsJDK anyway (9 to 20 s).

- 2026-09-17 (measurement): `mx build` in `vm/` also compiles the Truffle, compiler and NFI
  *test* projects (`com.oracle.truffle.api.bytecode.test` alone is 40 to 60 s on Windows) and the
  `native-image.exe` image costs ~2 min. `mx-env/ce-llvm-dev` could set `BUILD_TARGETS` (mx's env
  default for `mx build --dependencies`) to the GraalVM distribution, or `NATIVE_IMAGES=` to get
  a JVM-mode `native-image` launcher, if a cold Windows build ever needs to be faster.

- 2026-09-17 (research, no run): On x86_64 COFF, LLVM emits the Itanium LSDA into `.xdata` right after the
  personality RVA for any unrecognized personality (WinException.cpp `endFunction` → `emitExceptionTable`).
  libunwind's SEH mode returns exactly that pointer from `_Unwind_GetLanguageSpecificData`. The Java
  personality and `GCCExceptionTable` therefore need no change.
- 2026-09-17 (research): Windows images are linked by `cl.exe ... /link ...` (`WindowsCCLinkerInvocation`),
  not by lld-link. `LLVMCCompilerInvoker` (clang) is only used with `-H:+UseLLVMDataSection`.
- 2026-09-17 (research): ~~`CallingConv::GRAAL` (107) on Win64 lowers arguments with `CC_X86_Win64_C`
  and allocates no 32-byte shadow area (`isCallingConvWin64` is false for it). Consistent on both sides
  of Java-to-Java calls; C-ABI calls use the normal Win64 convention. Verified empirically in Task 8.~~
  **Superseded - Task 8 found the opposite for the C-callable entry stubs: the missing 32-byte home
  space makes every entry point with more than four arguments read argument five 32 bytes low (Win64
  puts it at return address + 40), which is most of the JNI function table, and `hello` faulted there.
  See the task 8 findings "the Graal calling convention is broken on Win64, and it is an LLVM bug",
  "the obvious workaround does not exist" and "the Win64 home space, before and after the LLVM fix"
  below, and the task 8 decision to patch LLVM (`isCallingConvWin64` now answers `isTargetWin64()` for
  `CallingConv::GRAAL`, released as `llvm-22.1.8-graal.3`).** What still holds: argument *registers*
  come from `CC_X86_Win64_C`, and C-ABI calls use the normal Win64 convention.
- 2026-09-17 (research): `x86_64-w64-windows-gnu` emits `___chkstk_ms`; `x86_64-pc-windows-msvc` emits
  `__chkstk`. Java code targets the msvc triple; libunwind is compiled for the gnu triple (needed for
  `__SEH__`) and linked as a COFF archive.
- 2026-09-17 (research): In SEH mode `struct _Unwind_Exception` has `uintptr_t private_[6]` (64 bytes),
  not `private_1/private_2` (32 bytes). The Java-side struct must be at least 64 bytes on Windows.
- 2026-09-17 (research): Oracle's darwin-aarch64 shadowed jars already contain
  `open module com.oracle.svm.shadowed.org.bytedeco.{llvm,javacpp}.macosx.arm64`; only `moduleName`
  is missing from suite.py. That is the whole GR-34811 blocker for the macOS backend.
- 2026-09-17 (spike, run https://github.com/Throwaway68/gha-graal/actions/runs/35207562231): **The Win64 LSDA is
  emitted for `x86_64-pc-windows-msvc` with a custom personality.** `llc -filetype=obj` on `tests/spike/win-eh/lsda.ll`
  (`invoke`/`landingpad`, `personality @__svm_seh_personality`) gives
  `Flags [ (0x3) ExceptionHandler (0x1) TerminateHandler (0x2) ]`, `Handler: __svm_seh_personality (0x8)` and
  `.xdata 0x8 IMAGE_REL_AMD64_ADDR32NB __svm_seh_personality`. The Itanium table follows the personality RVA in
  `.xdata`: `0000 19040100 04420000 00000000 ff001501 / 0010 08040510 01091600 00010000` — `0x19` = version 1 +
  flags 3, then the handler RVA, then `ff` (@LPStart omit), `00` (@TType absptr), `15` (ttbase), `01` (call site
  encoding uleb128). The assembly shows it verbatim: `.seh_handlerdata` / `GCC_except_table0:` /
  `.byte 1  # Call site Encoding = uleb128`. No LLVM change is needed for the Java personality.
- 2026-09-17 (spike, run https://github.com/Throwaway68/gha-graal/actions/runs/35207562231): **libunwind builds in SEH mode with the bundled clang.** `runtimes/` with
  `-DLLVM_ENABLE_RUNTIMES=libunwind`, `--target=x86_64-w64-windows-gnu` (predefines `__SEH__`, so `config.h` sets
  `_LIBUNWIND_SUPPORT_SEH_UNWIND` and `Unwind-seh.cpp` is compiled) and `-DCMAKE_SYSROOT=C:/msys64/ucrt64` builds in
  ~20 s and installs `lib/x86_64-w64-windows-gnu/libunwind.a`. It defines `_Unwind_RaiseException`, `_Unwind_Resume`,
  `_Unwind_DeleteException`, `_Unwind_Backtrace`, `_GCC_specific_handler`, `_Unwind_GetLanguageSpecificData`,
  `_Unwind_GetRegionStart`, `_Unwind_Get/SetIP`, `_Unwind_GetIPInfo`, `_Unwind_Get/SetGR`. Needed cmake options
  beyond the obvious: `-DCMAKE_TRY_COMPILE_TARGET_TYPE=STATIC_LIBRARY` (no mingw CRT to link against) and
  `-DLLVM_INCLUDE_TESTS=OFF` (the runtimes build otherwise does `add_subdirectory(<src>/llvm/utils/llvm-lit)`,
  run https://github.com/Throwaway68/gha-graal/actions/runs/35205903348).
- 2026-09-17 (spike, run https://github.com/Throwaway68/gha-graal/actions/runs/35206156310): **link.exe rejects the mingw-target objects as they come out of clang**:
  `libunwind.a(UnwindLevel1-gcc-ext.c.obj) : fatal error LNK1143: invalid or corrupt file: no symbol for COMDAT
  section 0x5`. Cause: whenever a function's section is a COMDAT (`-ffunction-sections`, which
  `HandleLLVMOptions.cmake` turns on, or a `linkonce_odr` C++ method such as
  `UnwindCursor<LocalAddressSpace, Registers_x86_64>::step`), LLVM emits the companion `.xdata$<fn>` / `.pdata$<fn>`
  as `IMAGE_COMDAT_SELECT_ANY` with no leader symbol, because "in a GNU environment, we can't use associative
  comdats" (llvm/lib/MC/MCStreamer.cpp). GNU ld keys those off the section name; link.exe wants a leader.
  `scripts/llvm/coff-assoc-comdats.py` rewrites exactly those section definitions to `IMAGE_COMDAT_SELECT_ASSOCIATIVE`
  pointing at the matching `.text$<fn>` — the form the MSVC target emits anyway. 88 sections in this archive; the
  edit is in place and size-preserving, so the archive index stays valid. Alternative, if this ever gets in the way:
  patch the GNU special case out of the LLVM fork.
- 2026-09-17 (spike, run https://github.com/Throwaway68/gha-graal/actions/runs/35207562231): **undefined symbols of `libunwind.a`** (archive-internal ones filtered
  out): `__imp_RaiseException`, `__imp_RtlCaptureContext`, `__imp_RtlLookupFunctionEntry`, `__imp_RtlRestoreContext`,
  `__imp_RtlUnwindEx`, `__imp_RtlVirtualUnwind` (all kernel32.lib), `__imp___acrt_iob_func`, `abort`, `fflush`,
  `memcpy` (ucrt.lib via `/MD`) and `fprintf`. `fprintf` is **not** in ucrt.lib — the UCRT headers define the printf
  family inline, so an object compiled against mingw's headers needs `legacy_stdio_definitions.lib`
  (`error LNK2019: unresolved external symbol fprintf referenced in function _Unwind_Resume_or_Rethrow`).
  Task 8 must add that library to the image link. `-mno-stack-arg-probe` keeps `___chkstk_ms` out of the archive;
  `-D__USE_MINGW_ANSI_STDIO=0` keeps `__mingw_*printf` out.
- 2026-09-17 (spike, run https://github.com/Throwaway68/gha-graal/actions/runs/35207562231): **link.exe takes the archive under either name**: linking the identical
  file as `libunwind.a` and as `unwind.lib` both succeed (`link.exe accepts the .a extension: yes`). The script
  still installs both names because Native Image builds library arguments as `<name>.lib`. The link prints
  `warning LNK4229: invalid directive '/exclude-symbols:...' encountered; ignored` once per hidden symbol (mingw's
  `-fvisibility=hidden` writes those into `.drectve`); harmless, silence with `/IGNORE:4229` if it gets noisy.
- 2026-09-17 (spike, run https://github.com/Throwaway68/gha-graal/actions/runs/35207562231): **an MSVC-built program can use the archive.**
  `cl /MD unwindtest.c unwind.lib kernel32.lib ntdll.lib legacy_stdio_definitions.lib` links, and the program walks
  15 frames through cl-compiled frames with `_Unwind_Backtrace`/`_Unwind_GetIP` (6 of them the recursive test
  function) and catches `_Unwind_RaiseException` with `__except (GetExceptionCode() == 0x20474343)`:
  `backtrace frames=15` / `caught STATUS_GCC_THROW` / `SPIKE OK`.
- 2026-09-17 (spike, run https://github.com/Throwaway68/gha-graal/actions/runs/35207562231): **`llc` starts without the `.exe` suffix.** Launching
  `D:\a\gha-graal\gha-graal\llvm\bin\llc` (no extension) through python's `subprocess` — same `CreateProcess`
  path as Java's `ProcessBuilder` — returns 0 and prints `LLVM version 22.1.8`. CreateProcess appends `.exe`, so the
  LLVM backend's extension-less tool paths need no Windows special case.
- 2026-09-17 (spike, run https://github.com/Throwaway68/gha-graal/actions/runs/35205641079): GNU tar on the runner cannot create the symlinks under `clang/test` and
  `llvm/utils` in `llvm-src-*.tar.gz` and then fails the whole extraction with exit 2. Extract only
  `cmake runtimes libunwind llvm/cmake third-party` (all the standalone runtimes build needs), or ignore tar's exit
  status and verify the directories afterwards.

- 2026-09-17 (run https://github.com/Throwaway68/gha-graal/actions/runs/35209720023): **the production Windows
  build reproduces the spike result.** `scripts/llvm/build.sh` calls `build-unwind-win.sh` with the LLVM install
  prefix as the out dir, so `package.sh` tars the archive into the main bundle unchanged. The step costs ~45 s of
  the 16-minute Windows job (warm sccache): MSYS2 at `C:\msys64` runs its first-time setup by itself, pacman pulls
  the UCRT headers, 11 ninja targets build, and `coff-assoc-comdats.py` makes 88 COMDAT sections in 9 objects
  associative. The undefined-symbol set is identical to the spike's (`__imp_Rtl*`, `__imp_RaiseException`,
  `__imp___acrt_iob_func`, `abort`, `fflush`, `fprintf`, `memcpy`).
- 2026-09-17 (review fix, runs 35209720023 → https://github.com/Throwaway68/gha-graal/actions/runs/35212270484):
  **an out dir that is an install prefix is a published bundle root.** The first graal.2 build shipped
  `build-unwind-win.sh`'s three diagnostic symbol lists (`libunwind-defined.txt`,
  `libunwind-undefined{,-raw}.txt`) at the root of `llvm-22.1.8-graal.2-windows-amd64.tar.gz`, and
  `LLVM_TOOLCHAIN` copies that root into every Windows GraalVM. The script now writes them into the build
  directory (still printed to the log, still uploaded by the spike workflow) and, as a regression guard,
  snapshots the regular files at the out dir's root before installing and fails if it added any. The
  republished bundle has 4080 entries and not one of them lives directly at the root.

- 2026-09-17 (run https://github.com/Throwaway68/gha-graal/actions/runs/35215356056): ~~**the windows-x86_64
  shadowed jars, for Task 6 to paste into suite.py verbatim** (sizes 1338481 and 620008997 bytes; digests
  re-verified after downloading the published assets):~~
  **Superseded - see the stock-jars decision (2026-09-17, controller ruling, task 6) in Decisions below.
  These URLs and digests never reached suite.py, which points every platform at the stock `org.bytedeco`
  Maven Central jars; they stay here as the record of what `jars-1.5.7-graal.1` contains.**
  - https://github.com/Throwaway68/gha-graal/releases/download/jars-1.5.7-graal.1/javacpp-shadowed-1.5.7-graal.1-windows-x86_64.jar
    `sha512:bc5e04f8b80cea785b0b6b9c0824030e5aeed99d5ed5b8610d9a9b895eb0a957f16c0660d87db6193892d3b2882ee74b1d7ad32d963007ba0a313d01ba94ce61`
    module `com.oracle.svm.shadowed.org.bytedeco.javacpp.windows.x86_64`
  - https://github.com/Throwaway68/gha-graal/releases/download/jars-1.5.7-graal.1/llvm-shadowed-13.0.1-1.5.7-graal.1-windows-x86_64.jar
    `sha512:64d5fead2d66e81c4c5ef3710e86bc2b16e8d2f8bddc7a63ebaa25ddad897d94c5839d0f99d5d038095b08878062a889f2459874e14ad90cdca66eaa7a3cd0d3`
    module `com.oracle.svm.shadowed.org.bytedeco.llvm.windows.x86_64`
  - `manifest.json`: https://github.com/Throwaway68/gha-graal/releases/download/jars-1.5.7-graal.1/manifest.json
- 2026-09-17 (research, `javap` on Oracle's linux-x86_64 and macosx-arm64 shadowed jars): **the shadowed
  platform jars are a pure repackaging.** They hold only native binaries (no `.class` files except the
  descriptor), so relocating `org/bytedeco/**` to `com/oracle/svm/shadowed/org/bytedeco/**` is entry
  renaming only - there is no bytecode to rewrite. `META-INF/versions/9/module-info.class` of every one of
  them is `open module com.oracle.svm.shadowed.org.bytedeco.<llvm|javacpp>.<os>.<arch> { requires transitive
  com.oracle.svm.shadowed.org.bytedeco.<llvm|javacpp>; requires java.base; }`, the manifest says
  `Multi-Release: true`, and there is no root descriptor, so `jar --describe-module` needs `--release 9`
  (without it: "No root module descriptor, specify --release", exit code 0). The base modules to compile
  against come from `https://lafo.ssw.uni-linz.ac.at/pub/graal-external-deps/native-image/` as
  `llvm-shadowed-13.0.1-1.5.7.jar` and `javacpp-shadowed-1.5.7.jar` (the `_1` names are 404); the llvm
  descriptor needs both on javac's module path, since the llvm module requires javacpp.

- 2026-09-17 (task 6, runs https://github.com/Throwaway68/gha-graal/actions/runs/35236400414 and
  https://github.com/Throwaway68/gha-graal/actions/runs/35236412885): **opening the backend for
  Windows takes five edits, and they hold.** `mx_substratevm.py` registers `ce_llvm_backend`
  unconditionally, suite.py points windows-amd64 at the `jars-1.5.7-graal.1` jars and gives
  darwin-aarch64 the `moduleName` it was missing, `LLVMFeature` adds `Platform.WINDOWS`,
  `getTargetTriple()` returns `-pc-windows-msvc` (so `x86_64-pc-windows-msvc`), `LLVMDirectives`
  returns no header and no library on Windows, and `LLVMExceptionUnwind`'s `@CConstant` reason
  codes plus the two `@CStruct` views become fixed Itanium values and a `@RawStructure`. Windows
  builds the GraalVM in 7m54s (10m55s for the job) and reaches the LLVM pipeline; Linux still prints `DEV-RUN OK`, which
  is what proves the header-free declarations changed no behaviour. Two things the edits taught:
  a `@RawStructure` field needs a getter **and** a setter (`InfoTreeBuilder.verifyRawStructFieldAccessors`
  rejects a lone getter), and a raw structure must not be nested in a `@CContext` class -
  `NativeLibraries.getDirectives` walks the enclosing types, so it would land in the LLVM context,
  and `RawStructureLayoutPlanner.plan` returns immediately for any context that is not the built-in
  one, leaving the field offsets unplanned. Both structures are therefore top-level types in
  `LLVMExceptionUnwind.java`. Their offsets come out right because the planner sorts by field size
  descending over an alphabetically ordered map: with eight one-word fields that is
  `exception_class` at 0, `exception_cleanup` at 8, `private0`..`private5` at 16..56, which is the
  C layout libunwind expects (it hands the first field's value to the personality function as its
  `exceptionClass` argument).

- 2026-09-17 (run https://github.com/Throwaway68/gha-graal/actions/runs/35236412885):
  **the windows-x86_64 shadowed jars do not work, because shadowing a JavaCPP jar is not entry
  renaming - it is a rebuild of the native libraries.** This corrects the finding above dated
  2026-09-17 ("the shadowed platform jars are a pure repackaging"): that check looked for `.class`
  files and found none, but the JNI names live inside the binaries. The Windows run fails at
  [5/8]/[6/8] with

  ```
  Error loading class org/bytedeco/javacpp/Loader.
  Error loading class org/bytedeco/javacpp/Loader.
  ```

  and then

  ```
  Caused by: jdk.graal.compiler.debug.GraalError: java.lang.NoClassDefFoundError: Could not initialize class com.oracle.svm.shadowed.org.bytedeco.llvm.global.LLVM
      at org.graalvm.nativeimage.llvm/com.oracle.svm.core.graal.llvm.util.LLVMIRBuilder.<init>(LLVMIRBuilder.java:97)
  Caused by: java.lang.ExceptionInInitializerError: Exception java.lang.NoClassDefFoundError: org/bytedeco/javacpp/Loader [in thread "ForkJoinPool.commonPool-worker-1"]
      at java.base/jdk.internal.loader.NativeLibraries.load(Native Method)
      ...
      at com.oracle.svm.shadowed.org.bytedeco.llvm/com.oracle.svm.shadowed.org.bytedeco.llvm.global.LLVM.<clinit>(LLVM.java:14)
  ```

  The DLL loads and its `JNI_OnLoad` then looks for the class it was generated against. `strings` on
  the payloads says why: Oracle's `libjnijavacpp.so` in
  `javacpp-shadowed-1.5.7_1-linux-x86_64.jar` exports
  `Java_com_oracle_svm_shadowed_org_bytedeco_javacpp_Pointer_allocate`, while our
  `jnijavacpp.dll` exports `Java_org_bytedeco_javacpp_Pointer_allocate` and embeds
  `org/bytedeco/javacpp/Loader`; `jniLLVM.dll` (75 MB, statically linked LLVM 13) has 2107
  `Java_org_bytedeco_*` symbols and zero shadowed ones. JavaCPP bakes the package name into the
  generated JNI sources at build time, so Oracle's platform jars were **rebuilt** from relocated
  sources (their `META-INF/maven/com.oracle.svm.shadowed.org.bytedeco/javacpp/pom.xml` says as
  much), and no amount of zip-entry renaming reproduces them. There is nothing to download either:
  every `*-windows-x86_64.jar` name under
  `https://lafo.ssw.uni-linz.ac.at/pub/graal-external-deps/native-image/` is a 404, and Maven
  Central has no `com.oracle.svm.shadowed.org.bytedeco` group at all - which is the real reason
  GR-34811 excludes Windows. Two ways out, both bigger than one task and both a controller
  decision: (a) build the natives, i.e. run JavaCPP's `Builder` on the already-shadowed classes
  from `javacpp-shadowed-1.5.7.jar` and `llvm-shadowed-13.0.1-1.5.7.jar` on a Windows runner -
  `jnijavacpp.dll` is self-contained and cheap, `jniLLVM.dll` needs LLVM 13.0.1 headers and static
  libs for MSVC, which the presets normally build from source; or (b) drop the shadowing on this
  branch, point all platforms at the stock `org.bytedeco` jars from Maven Central and rename the
  package in the 11 graal files that mention it plus suite.py and `SVM_LLVM`'s `moduleInfo` -
  cheap and mechanical, but it diverges from upstream everywhere.

- 2026-09-17 (runs https://github.com/Throwaway68/gha-graal/actions/runs/35238742378 and
  https://github.com/Throwaway68/gha-graal/actions/runs/35239767153, graal commit 6962b05ef22):
  **the reason GR-34811 also excludes darwin-aarch64 is a two-line manifest, not a missing port.**
  Registering `svml` there with the `moduleName` entries the plan expected makes `mx build` fail at

  ```
  java --describe-module com.oracle.svm.shadowed.org.bytedeco.llvm.macosx.arm64 failed. Please verify the moduleName attribute of LLVM_PLATFORM_SPECIFIC_SHADOWED.
  stdout:
  com.oracle.svm.shadowed.org.bytedeco.llvm.macosx.arm64 not found
  ```

  The module is there - `META-INF/versions/9/module-info.class` of
  `llvm-shadowed-13.0.1-1.5.7-macosx-arm64.jar` names
  `com.oracle.svm.shadowed.org.bytedeco.llvm.macosx.arm64` - but the whole manifest of that jar and
  of `javacpp-shadowed-1.5.7-macosx-arm64.jar` is `Manifest-Version: 1.0` plus
  `Created-By: 20.0.1 (Oracle Corporation)`, with no `Multi-Release: true`, so nothing under
  `META-INF/versions/` is ever consulted. The linux jars have the attribute (their manifest is
  2255 bytes of OSGi metadata from the original bytedeco build; the darwin-aarch64 ones were
  clearly repackaged with plain `jar`, losing it). Their natives are fine - `nm` on
  `libjnijavacpp.dylib` shows 108 `Java_com_oracle_svm_shadowed_org_bytedeco_javacpp_*` exports and
  the shadowed `FindClass` strings, i.e. these were built the way the windows ones would have to
  be. So darwin-aarch64 is one re-manifested pair of jars away from a working LLVM backend, which
  is a jar to publish rather than a source change; ~~this branch therefore keeps
  `llvm_supported = not (mx.is_darwin() and mx.get_arch() == "aarch64")` and leaves the two
  darwin/aarch64 suite.py entries byte-identical to upstream. With that, darwin-aarch64 is back to
  the pristine tag's behaviour: the GraalVM builds and `dev-run` stops at
  `Error: Unknown name in option specification: tool:llvm-backend` (exit 20), the same way the tag
  behaves on Windows.~~ **Superseded - the stock-jars decision (2026-09-17, controller ruling, task 6)
  changed this: the branch has `llvm_supported = True` and points darwin-aarch64 at the stock
  macosx-arm64 `org.bytedeco` jars too, so the backend is registered there and fails later, in `llc`
  - see the finding "darwin-aarch64 is no longer blocked by its jars, it is blocked by our LLVM build"
  below and the task 9 `x27`/`x28` finding at the end of this section.**

- 2026-09-17 (runs https://github.com/Throwaway68/gha-graal/actions/runs/35241867510,
  https://github.com/Throwaway68/gha-graal/actions/runs/35242758887 and
  https://github.com/Throwaway68/gha-graal/actions/runs/35242773448, graal commits 728e8da48ff and
  ae2a36f7040): **what dropping the shadowing costs, end to end.** The four suite.py libraries keep
  their names - `LLVM_WRAPPER_SHADOWED`, `JAVACPP_SHADOWED`, `LLVM_PLATFORM_SPECIFIC_SHADOWED`,
  `JAVACPP_PLATFORM_SPECIFIC_SHADOWED`, so `tool-llvm.properties`' `ImageBuilderModulePath` and
  SVM_LLVM's `exclude` list are untouched - and now point at
  `https://repo1.maven.org/maven2/org/bytedeco/{llvm/13.0.1-1.5.7,javacpp/1.5.7}`. The module names
  are what the jars declare (`javap` on their `META-INF/versions/9/module-info.class`):
  `org.bytedeco.llvm`, `org.bytedeco.javacpp` and `org.bytedeco.<llvm|javacpp>.<os>.<arch>`; all
  twelve say `Multi-Release: true`, unlike Oracle's macosx-arm64 pair. Every digest was computed
  from the downloaded bytes and cross-checked against Maven Central's published `.sha1` - 14 of 14
  match, 936 MB. `linux-riscv64` has no 13.0.1-1.5.7 build, so that entry is gone and riscv64 falls
  to `"<others>": {"optional": True}`. In the sources it is 42 imports across 10 files of
  `com.oracle.svm.core.graal.llvm` plus the two class names in `SVMHost`'s shared-layer forbidden
  module list.

  One thing does not follow from a rename: `NativeImageGeneratorRunner.checkBootModuleDependencies`
  rejects anything the builder modules read outside a fixed allowlist, and the LLVM backend's
  exemption there is spelled `startsWith("com.oracle.svm.shadowed.")`. Stock jars therefore stopped
  the build before it started, on every platform:

  ```
  Fatal error: com.oracle.svm.shared.util.VMError$HostedError: Unexpected image builder module-dependencies: jdk.unsupported, org.bytedeco.javacpp.linux.x86_64, org.bytedeco.llvm.linux.x86_64, org.bytedeco.javacpp, org.bytedeco.llvm
  ```

  (`jdk.unsupported` shows up only because the walk now enters `org.bytedeco.javacpp`, which
  requires it; the shadowed module was skipped before it could be entered.) The exemption now
  covers `org.bytedeco.` as well.

- 2026-09-17 (runs https://github.com/Throwaway68/gha-graal/actions/runs/35241895761 and
  https://github.com/Throwaway68/gha-graal/actions/runs/35242787328): **darwin-aarch64 is no longer
  blocked by its jars, it is blocked by our LLVM build.** With the stock macosx-arm64 jars the
  module resolves, `mx build` archives SVM_LLVM, and `native-image --tool:llvm-backend` gets
  through `[7/8] Laying out methods` before every batch fails in `llc`:

  ```
  LLVM compilation failed for batch 1 (f1000-f2000) ... : 1
  Command: llc -relocation-model=pic --trap-unreachable -march=aarch64 --frame-pointer=all --aarch64-frame-record-on-top -O2 -filetype=obj -o b1.o b1o.bc
  ```

  ~~`--aarch64-frame-record-on-top` is a GraalVM patch to LLVM and
  `Throwaway68/llvm-project@graal/22.1.8` does not carry it (`frame-record-on-top` appears zero
  times in `llvm/lib/Target/AArch64/AArch64FrameLowering.cpp` on both of its branches). It is an
  aarch64-only flag - amd64 passes `-march=x86-64` and nothing like it - so it does not touch the
  Windows port and was not investigated further. Anyone who wants darwin-aarch64 or linux-aarch64
  green needs that patch in the LLVM release first.~~ **Superseded - the second sentence is wrong;
  see the correction dated 2026-09-17 (task 8 review) below.** What still holds: the flag is
  aarch64-only, amd64 passes `-march=x86-64` and nothing like it, so none of this touches the
  Windows port.

- 2026-09-17 (the user's tip): GitHub Actions runners can be reached over **ssh for interactive
  debugging** (a tmate/upterm-style step), which beats a full workflow round trip per attempt when
  the same 10-minute Windows job is being poked at repeatedly. `graalvm-dev.yml` now has an opt-in
  `debug_ssh` input (default off) that runs `mxschmitt/action-tmate@v3.24` after `dev-run`,
  whether or not it failed, with `limit-access-to-actor: true` - this repository is public and the
  connection string lands in the log, so the dispatching account needs a public key at
  https://github.com/settings/keys for the session to be usable.

- 2026-09-17 (run https://github.com/Throwaway68/gha-graal/actions/runs/35248532685): **what the
  single Windows object looks like.** `llvm.obj` of the `hello` program, 5.0 MB, COFF-x86-64, 53
  sections, read from the artifact with `llvm-readobj`/`llvm-nm` 22.1.8:

  | section | raw size | relocs | holds |
  |---------|---------:|-------:|-------|
  | `.text` | 1,516 | 0 | the 22 `__llvm_jni_wrapper_*` transition wrappers |
  | `.text$svm0` | 0 | 0 | `__svm_code_section` |
  | `.text$svm1` | 2,517,614 | 55,623 | 5,249 Java methods, 5,451 symbols |
  | `.text$svm2` | 0 | 0 | `__svm_text_end` |
  | `.pdata` (2) | 62,988 + 252 | 15,747 + 63 | one 12-byte RUNTIME_FUNCTION per Java method |
  | `.xdata` (2) | 170,124 + 272 | 5,249 + 0 | SEH unwind info, one personality reloc per method |
  | `.rdata` (43) | 19,588 + small | 4,897 | jump tables and constants |

  `llvm-nm` shows `__svm_code_section` and `__svm_text_end` as `T` at offset 0 of their marker
  sections. There is exactly one `.text$svm1`, which is what makes the exact-name lookup in
  `parseCode` work. `b0.o`, the same object before `llvm-objcopy`, additionally carries
  `.llvm_stackmaps` at 5,040,488 bytes - half the file - so stripping it is not cosmetic.

  Two differences from linux to keep in mind. The `__llvm_jni_wrapper_*` functions come from
  `LLVMGenerator.createJNIWrapper`, not from `addMainFunction`, so they keep the default section and
  end up *outside* `[__svm_code_section, __svm_text_end)`, where on linux everything shares `.text`.
  They should never be the target of a code-info lookup - the wrapper stores its *caller's* return
  address into the JavaFrameAnchor, which is the whole point of it - but it is a difference. The
  `LinkOnce` helpers of `LLVMHelperFunctions`, which do get the code section, turn into COFF weak
  externals inside `.text$svm1` rather than into separate COMDAT sections, so they cannot confuse
  the section lookup either.

- 2026-09-17 (local experiment with the darwin bundle of `llvm-22.1.8-graal.2`): **grouped sections
  put plain `.text` first, and the end marker is padded.** Two objects - one with
  `.text$svm0`/`.text$svm1`/`.text$svm2` exactly as the backend now emits them, one with an ordinary
  `.text` function - linked with `lld-link /dll /noentry` give a single `.text` of 0x40 bytes: the
  plain `.text` function at +0x00, then `.text$svm0` (empty) and the three `.text$svm1` functions at
  +0x10, then `.text$svm2` at +0x40. A contribution without a `$` suffix sorts before every
  `.text$*` one, which is why the JNI wrappers cannot land between the two markers, and MSVC's own
  code is in `.text$mn` ("mn" < "svm0"), so it cannot either. The end marker is aligned up by its
  `.p2align 4`: for the real object `__svm_text_end - __svm_code_section` will be 2 bytes more than
  the 2,517,614 `parseCode` reports as the code area size (2517614 % 16 == 14). Whatever consumes
  the two symbols at runtime has to tolerate that.

- 2026-09-17 (runs https://github.com/Throwaway68/gha-graal/actions/runs/35245894558 and
  https://github.com/Throwaway68/gha-graal/actions/runs/35247213695): **two things the single-batch
  design breaks that have nothing to do with sections.** First, one batch means one bitcode file per
  method on the `llvm-link` command line - 5,249 of them, about 47 kB - and Windows caps a command
  line at 32,767 characters:

  ```
  Cannot run program "...\lib\llvm\bin\llvm-link" (in directory "...\llvm"):
  CreateProcess error=206, The filename or extension is too long
  ```

  LLVM tools expand `@`-response files in `InitLLVM`, before command line parsing, so the inputs now
  go into `b0.bc.rsp`, one per line (verified against llvm-link 22.1.8 locally before pushing).
  Second, `WindowsUnwindInfoFeature` derives `.pdata`/`.xdata` from the prologue code marks of every
  compilation, and the LLVM backend records none, so the first run that reached `[8/8] Creating
  image` died in it with `Cannot read field "id" because "prologueMarks[i]" is null`. The feature has
  nothing to do under this backend either - `llvm.obj` brings its own `.pdata`/`.xdata` - so it now
  stays out of the configuration when `SubstrateOptions.useLLVMBackend()` holds.

  Both were found only because the error message now carries the tool's own output: `nativeLink` and
  friends used to log it to `debug.log`, which needs `-H:Log` to reach the console. The one helper
  that appends `e.getOutput()` to all seven `GraalError` messages of `LLVMToolchainUtils` is the
  cheapest change in this task and paid for itself twice.

- 2026-09-17 (runs https://github.com/Throwaway68/gha-graal/actions/runs/35242773448,
  .../35248532685 and .../35248894118): **the single batch costs about 20 s of wall clock on
  `hello`.** `[7/8] Laying out methods` - the phase that runs the `(bitcode)`, `(prelink)`, `(llvm)`
  and `(postlink)` timers - takes 40.3 s on windows-amd64 with one batch, against 20.1 s on the same
  runner class with the default six batches (task 6's run, which then failed in `lld-link`), and
  16.0 s on linux-amd64 with six batches. `opt` and `llc` are the bulk of it and they are now a
  single process on one core; the batch executor has nothing left to parallelize. For `hello` this is
  noise next to the 7-minute GraalVM build, but it scales with the program, and a real image will
  feel it. If it ever matters, the way out is not more batches - PE/COFF still cannot link them - but
  `llc -j`-style parallelism inside one module, or splitting into several objects that all use
  `.text$svm1` and letting the image linker concatenate them.

- 2026-09-17 (graal commit 999fc4f25e7, run https://github.com/Throwaway68/gha-graal/actions/runs/35252597474):
  **the Windows image links and runs; the SEH shim and libunwind are in place.** `cl.exe` accepts
  `unwind.lib` (a copy of `lib/x86_64-w64-windows-gnu/libunwind.a` in the image temp directory) as an
  input file plus `kernel32.lib`, `ntdll.lib` and `legacy_stdio_definitions.lib` through
  `addNativeLinkerOption`, and the five `_Unwind_*` symbols resolve. `app.exe` starts, initializes the
  isolate, runs `JavaMainWrapper` and reaches `Hello.main` and `System.out.println` - the whole startup
  path of a Native Image runs LLVM-compiled code with the grouped-section layout of task 7.

- 2026-09-17 (same run, evidence read back from the artifact's `llvm.obj` with `objdump`):
  **the marker/offset layout is exactly as designed, and no offset fix-up is needed.**
  `.text$svm0` and `.text$svm2` are both 0 bytes and hold `__svm_code_section` and `__svm_text_end` at
  offset 0. `.text$svm1` is 0x266a6e bytes and its first symbol at offset 0 is a real Java method
  (`InvalidMethodPointerHandler_invalidCodeAddressHandler_...`), which is what makes the image's
  `codeStart` correct: it is a `MethodPointer` to the first compilation, and every method's
  `codeAddressOffset` is relative to the start of that section. The SEH glue sits in its own
  `.text$svm3` (0x3b bytes). Nothing at run time reads `__svm_code_section` or `__svm_text_end` - they
  exist only because `NativeImage.build` declares them undefined when the code cache does not define
  them - so the 16-byte alignment of `.text$svm2` (`.p2align 4`), which can leave `__svm_text_end` up to
  15 bytes past the last function, is harmless and stays.

- 2026-09-17 (same run, `objdump -h`): **plain `.text` is not empty: it holds the 22
  `__llvm_jni_wrapper_*` transition wrappers** (0x5ec bytes), because `LLVMGenerator.createJNIWrapper`
  does not set a section while `LLVMHelperFunctions` does. They therefore live outside
  `[__svm_code_section, __svm_text_end)`. That is harmless: the wrapper stores its *caller's* return
  address in the `JavaFrameAnchor` (`buildReturnAddress(0)`), so no stack walk ever resolves a wrapper
  PC - confirmed in the crash dumps below, where `LastJavaIP` resolves to `FileOutputStream.writeBytes`.
  Left alone on purpose, see the decisions.

- 2026-09-17 (runs https://github.com/Throwaway68/gha-graal/actions/runs/35252597474 and
  https://github.com/Throwaway68/gha-graal/actions/runs/35253878368): **the Graal calling convention is
  broken on Win64, and it is an LLVM bug.** `System.out.println` ends in `FileOutputStream.writeBytes`
  in `libjava.dll`, which calls back through the JNI function table; the image died in
  `GetByteArrayRegion(env, array, start, len, buf)` with an access violation inside the copy. The entry
  point stub reads its fifth argument from the wrong slot:

  ```
  IsolateEnterStub__JNIFunctions__GetByteArrayRegion__...:
      push rbp; push r15; push r14; push r13; push r12; push rsi; push rdi; push rbx
      sub  rsp, 0x18
      lea  rbp, [rsp+0x10]        ; rbp = entry rsp - 72
      ...
      mov  rsi, [rbp+0x50]        ; = entry rsp + 8
  ```

  Win64 puts the fifth argument at *return address + 40*: the caller reserves 32 bytes of home space.
  `X86Subtarget::isCallingConvWin64` lists the conventions that get it and ends in `default: return
  false`, and `CallingConv::GRAAL` (107, "Used by GraalVM. Two additional registers are reserved.")
  falls into that default. So the Graal convention on Win64 is "Win64 argument registers, no home
  space", and every entry point that C calls with more than four arguments is broken - which is most of
  the JNI function table.

- 2026-09-17 (run https://github.com/Throwaway68/gha-graal/actions/runs/35253878368): **the obvious
  workaround does not exist: the Graal calling convention is what reserves the registers.**
  Compiling entry points with LLVM's C convention instead (graal commit fdfa9444838) fixed the home
  space and broke everything else, one JNI call earlier: `GetArrayLength` faulted at
  `movq 0x8(%r15), %rax`, the stack overflow check reading the isolate thread out of R15.
  `X86RegisterInfo::getReservedRegs` reserves R14 and R15 *iff* the function's calling convention is
  `CallingConv::GRAAL`; without it the two `llvm.write_register` calls of
  `InitializeReservedRegistersPrologue` define ordinary allocatable registers whose defs are dead, and
  LLVM deletes them - the stub simply no longer contains the `movq 0xd0(%rcx), %r14` /
  `movq %rcx, %r15` pair that the same stub has under the Graal convention. There is no X86
  subtarget feature to reserve a register independently of the calling convention.


- 2026-09-17 (task 8, runs https://github.com/Throwaway68/gha-graal/actions/runs/35252597474 and
  https://github.com/Throwaway68/gha-graal/actions/runs/35285287516, `llvm.obj` read from both
  artifacts): **the Win64 home space, before and after the LLVM fix, in one entry point.**
  `IsolateEnterStub_JNIFunctions_GetByteArrayRegion` takes five arguments
  (`env, array, start, len, buf`), so it is exactly the case `CC_X86_Win64_C` without a 32-byte
  home space gets wrong, and it is on `System.out.println`'s path.

  ```
  graal.2 (isCallingConvWin64 false for GRAAL)   graal.3 (true)
  push rbp,r15,r14,r13,r12,rsi,rdi,rbx           push rbp,r15,r14,r13,r12,rsi,rdi,rbx
  sub  rsp, 0x18                                 sub  rsp, 0x38
  lea  rbp, [rsp+0x10]                           lea  rbp, [rsp+0x30]
  mov  rsi, [rbp+0x50]   ; = entry rsp + 8       mov  rsi, [rbp+0x70]   ; = entry rsp + 40
  mov  r14, [rcx+0xd0]                           mov  r14, [rcx+0xd0]
  mov  r15, rcx                                  mov  r15, rcx
  ```

  Win64 puts argument 5 at `entry rsp + 40` (return address plus the caller's 32-byte home space),
  so the left column reads the buffer pointer 32 bytes low - it lands on the stub's own saved
  registers - and the image faulted in `JNIFunctions$Support.getPrimitiveArrayRegion`. The right
  column is correct, and the two `mov`s of the reserved registers survive in both: the function is
  still on `CallingConv::GRAAL`, which is what makes `X86RegisterInfo::getReservedRegs` reserve R14
  and R15. The frame grew by exactly 32 bytes, and the stub now also reserves home space for its
  own calls (`mov [rsp+0x20], rsi` passes argument 5 onward at the Win64 slot). So yes, a Java
  entry point with more than four arguments runs in the green image; `hello` reaches ten-argument
  wrappers too (`__llvm_jni_wrapper_f_i64i64i64i64i64i32i32i64i32i32f_native` is in the object).

- 2026-09-17 (task 8, run https://github.com/Throwaway68/gha-graal/actions/runs/35285287516):
  **`__chkstk` never appears, so the msvc/mingw stack-probe mismatch stayed theoretical.**
  `objdump -t llvm.obj` of the green image has zero symbols matching `chkstk` - neither `__chkstk`
  (what `x86_64-pc-windows-msvc` emits) nor `___chkstk_ms` (what `x86_64-w64-windows-gnu` emits).
  No Java frame in `hello` reaches a page, and libunwind is built with `-mno-stack-arg-probe`
  (finding above), so neither side asks for a probe. A program with a large frame will pull
  `__chkstk` out of the MSVC CRT, which `cl.exe /MD` links anyway; the mingw-side symbol is the one
  that would have no provider, and it is not there.

- 2026-09-17 (task 8, run https://github.com/Throwaway68/gha-graal/actions/runs/35285287516):
  **the final Windows link inputs.** `WindowsCCLinkerInvocation` runs `cl.exe /MD <image objects>
  <temp>/unwind.lib /link ... <the usual advapi32/ws2_32/... set> kernel32.lib ntdll.lib
  legacy_stdio_definitions.lib`. The last four entries are what `LLVMFeature.beforeImageWrite` adds
  on Windows and nothing else in the build knows about: `unwind.lib` is a copy of
  `<graalvm>/lib/llvm/lib/x86_64-w64-windows-gnu/libunwind.a` placed in the linker's temp directory
  (cl.exe forwards an unrecognized extension to the linker as it is, and the temp directory is what
  `CCLinkerInvocation` relativizes against), `kernel32.lib` and `ntdll.lib` provide the `Rtl*`
  unwinding imports of libunwind's SEH mode, and `legacy_stdio_definitions.lib` provides `fprintf`,
  which the UCRT headers define inline and `ucrt.lib` therefore does not export. The link resolves
  with no unresolved externals; `dumpbin /headers app.exe` reports PE32+ x64, subsystem 3
  (Windows CUI), entry point `0x1a1e4`, image size `0x725000`.

- 2026-09-17 (task 8, run https://github.com/Throwaway68/gha-graal/actions/runs/35284146085):
  **the first green image was reported as a failure by the test harness, over carriage returns.**
  The run printed both program lines, `stderr` was empty and the process exited 0, and `dev-run.sh`
  still ended in `missing expected line: args=0`. The image writes CRLF (`stdout.txt` in the
  artifact is `...2022\r\nargs=0\r\n`) and `expected.txt` arrives on the runner with CRLF of its
  own - the Windows checkout converts line endings, which this journal already noted for `suite.py`
  and `hashFiles`. So `grep -qF -- "$line" stdout.txt` searched for `args=0\r`. A GNU or BSD grep
  finds that inside `args=0\r\n` and the check passes; Git Bash's grep evidently treats its input as
  text and strips the `\r` from the line it compares while keeping it in the pattern, so the same
  pair does not match there - which is also why the case cannot be reproduced off Windows. Both
  sides are stripped before comparing now (`tr -d '\r'` on the output, `${line%$'\r'}` on the
  expectation), which is correct under either grep. Worth remembering for every
  future Windows expectation in this repository - and worth reading a "failed" Windows dev run's
  `stdout.txt` before believing it. The same run also showed `dumpbin` failing with `LNK1181:
  cannot open input file '...\work\app'`: MSYS's `stat()` appends `.exe` by itself, so
  `[ -e "$W/app" ]` is true on Windows and the diagnostics were handed an extension-less path.

- 2026-09-17 (task 8, runs https://github.com/Throwaway68/gha-graal/actions/runs/35255939184 and
  https://github.com/Throwaway68/gha-graal/actions/runs/35282186301): **`gh release create <tag>
  assets/*` cannot publish this bundle, and a failed upload takes the release with it.** Five
  attempts at `llvm-22.1.8-graal.3` from run 35255939184 died in `HTTP 500: Error saving asset`
  from uploads.github.com on the ~1 GB tarballs, and `gh release create` deletes the release it
  just made when any asset fails, so each attempt left nothing behind and all three platform builds
  had to be kept alive as artifacts. `llvm.yml` now creates the release as a **draft with no
  assets**, uploads each file on its own with up to six attempts a minute apart
  (`gh release upload --clobber`), verifies every published asset against the local file's size and
  its `uploaded` state, and only then clears the draft flag; an existing *published* release of the
  same tag aborts the job instead of being touched. On run 35282186301 all seven assets went up on
  the first attempt in 2m06s total, which suggests the 500s came from `gh`'s five-way concurrent
  upload rather than from size alone - one at a time is both slower and reliable.

- 2026-09-17 (task 8 review, correction to the darwin-aarch64 finding above): **the LLVM fork does
  carry `--aarch64-frame-record-on-top`, so that is not why `llc` rejects the aarch64 batches.**
  The earlier check grepped `llvm/lib/Target/AArch64/AArch64FrameLowering.cpp`, which is the wrong
  file. The option is defined in `llvm/lib/Target/AArch64/AArch64RegisterInfo.cpp`:

  ```
  static cl::opt<bool>
      FrameRecordOnTop("aarch64-frame-record-on-top",
                       cl::desc("place the frame record on top of the frame"),
                       cl::init(false), cl::Hidden);
  ```

  It comes from GraalVM patch commit `59be06d2` ("Introduce option to force placement of the frame
  record on top of the stack frame"), which touches that one file, and it is present on **both**
  `Throwaway68/llvm-project@graal/22.1.8` and `@graal/22.1.8-win` (the fork has three branches now:
  those two and `main`; the superseded entry's "both of its branches" predates `graal/22.1.8-win`).

  So the `LLVM compilation failed for batch 1` above needs a different explanation, and it is
  **open for round 2** - it was not investigated here. The flag being aarch64-only still means none
  of this can affect windows-amd64 or linux-amd64, and `llvm-22.1.8-graal.2` and `graal.3` are
  unaffected as far as the amd64 targets are concerned.

- 2026-09-17 (task 8 review, run https://github.com/Throwaway68/gha-graal/actions/runs/35262580562):
  **`debug_ssh` is linux/macOS only, and the workflow now enforces that.** `mxschmitt/action-tmate@v3.24`
  in `detached: true` mode never returns on windows-2022: that run sat in the tmate step for 57
  minutes without reaching the publishing step and had to be cancelled. Attached mode is no use
  either, because a job's log is not readable through the API while the job runs, so the connection
  string never reaches the caller (run 35260481484). The whole ssh block in `graalvm-dev.yml` is
  therefore skipped when `runner.os == 'Windows'`, with a `::warning::` saying why, and every step
  in it carries its own `timeout-minutes` again (45 for tmate, which had been lost when `detached`
  was added, 5/10 for the publishing steps, 180 for the hold) so that `debug_ssh: true` can never
  burn the job's 240-minute budget. Debugging a Windows runner interactively means starting tmate
  by hand from MSYS2 in a `run:` step; nobody has done that yet. This supersedes the "runs after
  `dev-run`" wording of the entry above for windows-amd64.

- 2026-09-17 (task 9, release run https://github.com/Throwaway68/gha-graal/actions/runs/35288617506):
  **darwin-aarch64 fails in the smoke test's LLVM backend step, and not over the frame-record
  option.** The full CE build (`ce-llvm-ci`) succeeds on macos-14 and `java`, `native-image`, `lli`
  and the Sulong C hello world all pass; `native-image --tool:llvm-backend` then gets through
  `[7/8] Laying out methods` and dies when `llc` rejects the batches (job 23:50:53 -> 00:17:46,
  26m53s; the backend step itself is 47.2s):

  ```
  > com.oracle.graal.pointsto.util.ParallelExecutionException: LLVM compilation failed for batch 1 (f1000-f2000). Use -H:LLVMMaxFunctionsPerBatch=1 to compile each method individually. (/var/folders/.../SVM-15247345571989107718/llvm/b1o.bc): 1
  Command: llc -relocation-model=pic --trap-unreachable -march=aarch64 --frame-pointer=all --aarch64-frame-record-on-top -O2 -filetype=obj -o b1.o b1o.bc
  error: <unknown>:0:0: invalid register "x28" for llvm.read_register
  error: <unknown>:0:0: invalid register "x27" for llvm.write_register
  ```

  (those two error lines repeat for every occurrence, hundreds of times). So `llc` accepts
  `--aarch64-frame-record-on-top` - the correction above was right that the option exists - and what
  it refuses is `llvm.read_register`/`llvm.write_register` on `x27` and `x28`, the registers
  SubstrateVM reserves for the heap base and the thread pointer. LLVM only lets those intrinsics
  name a register that is reserved for the target, so the missing piece is on the
  `-mattr`/reserve-register side of the darwin invocation, not in the frame layout. **Open for round
  2, not investigated here**; it cannot affect amd64, where the backend is green on both platforms.
  Round 1's release is therefore built from linux-amd64 and windows-amd64 only.

- 2026-09-17 (final review, no run): **what round 2 should verify.** Round 1's evidence comes from
  `hello` plus offline reads of `llvm.obj`, which leaves these open, each cheap to run through
  `graalvm-dev.yml` with a purpose-built program:
  - a throw/catch **across an MSVC-compiled JNI frame** (Java -> JNI -> Java -> throw, caught in the
    outer Java frame): the one path where libunwind's SEH mode has to restore R14/R15 through frames
    it did not compile. `hello` only unwinds within LLVM-compiled code.
  - the **`StackOverflowError` path through `protectYellowZone`**: recursion deep enough to hit the
    yellow zone and recover, which exercises the stack-boundary code with the new Win64 frame layout.
  - a **large-frame method** (a frame bigger than a page) so `__chkstk` is actually emitted and the
    msvc/mingw stack-probe question stops being theoretical - see the `__chkstk` finding above, where
    zero probe symbols appear in `hello`.
  - the darwin **`x27`/`x28` reserved-register rejection** in `llc` (the task 9 finding above), which
    is what keeps darwin-aarch64 out of the release.
  - **JNI wrappers in plain `.text`**: they sit outside `[__svm_code_section, __svm_text_end)` by
    design; a program that stack-walks from inside a wrapper would confirm the reasoning empirically.
  - the Windows native-image **"2 warnings"** nobody has read yet: retrieve them from a
    `graalvm-dev.yml` run's work-dir artifact (`work/stdout.txt` / `work/stderr.txt`).

- 2026-09-18 (round 2, task 1, spike run https://github.com/Throwaway68/gha-graal/actions/runs/35325048211):
  **what an ssh session on windows-2022 needs.** `scripts/graalvm/win-ssh.ps1` sets it up in 51 s and
  the pieces are all load-bearing:

  - **The OpenSSH server is a Windows capability, and it is not preinstalled.**
    `Get-WindowsCapability -Online -Name OpenSSH.Server*` says `NotPresent` on the
    windows-2022 image, and `Add-WindowsCapability` takes **40 s** - fast enough that the MSYS2
    `pacman -S openssh` fallback the plan allowed was never needed. The script still bounds the
    install at 180 s (a `Start-Job` plus `Wait-Job -Timeout`) and names the fallback in the error,
    because a DISM install that hangs would otherwise eat the step's whole timeout.
  - **`administrators_authorized_keys`, not `~/.ssh/authorized_keys`.** The default sshd_config ends
    in a `Match Group administrators` block that redirects `AuthorizedKeysFile` to
    `C:\ProgramData\ssh\administrators_authorized_keys`, and `runneradmin` is an administrator, so
    keys in the home directory are ignored. sshd also refuses the file unless it is owned by
    Administrators/SYSTEM alone, hence the `icacls /inheritance:r` line. The keys themselves are the
    dispatching account's (`https://github.com/<actor>.keys`), the same rule as tmate's
    `limit-access-to-actor`. `PasswordAuthentication no` is not enough on its own: the stock
    Windows sshd_config carries no `KbdInteractiveAuthentication` line at all (run 35327752826), so
    that default-on, password-backed method would stay open for an administrator account. The
    script prepends `AuthenticationMethods publickey` and `KbdInteractiveAuthentication no` -
    prepended because sshd takes a keyword's first value and because the file ends in the `Match`
    block. Verified from the Mac in run 35328169055: key auth gets a shell, while
    `ssh -o PreferredAuthentications=keyboard-interactive,password -o PubkeyAuthentication=no`
    is answered with `Permission denied (publickey)`.
  - **`DefaultShell` needs `DefaultShellCommandOption` beside it.** `HKLM:\SOFTWARE\OpenSSH\DefaultShell`
    = Git bash gives `MINGW64_NT-10.0-20348 ... x86_64 Msys` as the login shell, but sshd builds a
    non-interactive `ssh <host> '<command>'` as `<shell> <DefaultShellCommandOption> <command>`,
    which defaults to cmd.exe's `/c` - bash would treat that as a file name. With `-c` (and
    `DefaultShellEscapeArguments` 0, so quotes survive) both session kinds work.
  - **sshd is a service and inherits nothing from the step.** The MSVC variables, `GRAALVM_HOME`,
    `JAVA_HOME`, `MX_PATH`, `MX_URLREWRITES` and `GITHUB_WORKSPACE` are dumped into
    `~/.gha-env.sh`, which `.bashrc`/`.bash_profile` source for interactive logins and a
    machine-wide **`BASH_ENV`** (set before sshd starts, so sshd's children inherit it) sources for
    `ssh <host> '<command>'`, which reads neither dot file. The file is guarded by an exported
    `GHA_ENV_SOURCED`, because `BASH_ENV` fires again in every subshell - `dev-run.sh` alone would
    otherwise re-prepend the whole PATH a dozen times.
  - **PATH is the one variable that cannot be copied verbatim, and CRLF cannot be used at all.**
    A `shell: bash` step gets the POSIX form of the Windows PATH because the MSYS runtime converts
    what it inherits; an `export PATH='C:\...;C:\...'` written from inside bash is not converted, and
    the session then has not even `ls`. The script hands the Windows list to `cygpath -up` instead.
    Every file it writes is LF and BOM-free (`[IO.File]::WriteAllText`): a CR ends up *inside* the
    value of the line it terminates, so `export FOO='bar'` would export `bar\r`;
    `administrators_authorized_keys` is written the same way rather than trusting sshd to shrug a
    stray CR off.
  - **cloudflared quick tunnel, no inbound port.** `cloudflared tunnel --url tcp://localhost:22`
    publishes `https://<name>.trycloudflare.com` in its log after ~3 s; the local end reaches it with
    `ssh -o ProxyCommand='cloudflared access tcp --hostname %h'`. The hostname goes into artifact
    `ssh-<platform>`, not into the log, because a job's log is not readable through the API while the
    job runs - the same reason the tmate block publishes an artifact.


## Decisions

- 2026-09-17 (controller ruling, task 6): **this branch uses the stock `org.bytedeco` jars from
  Maven Central on every platform**, not Oracle's `com.oracle.svm.shadowed.org.bytedeco` builds.
  The shadowing exists so that a user classpath which also uses JavaCPP cannot clash with the
  builder's copy; that isolation is worth less here than having the LLVM backend run on Windows at
  all, and the shadowed artifacts simply do not exist for windows-x86_64 (see the finding on their
  native symbol names). The price is divergence from upstream in 11 files the port would otherwise
  not touch. Consequence: the release `jars-1.5.7-graal.1` built in task 4 is **unused** - nothing
  references it any more. It stays published as the record of what was tried.

- 2026-09-17 (controller ruling, task 5 review): the dev workflow caches **only** mx's downloads.
  No cache of build outputs, and no timestamp manipulation of the checkout, the JDK or `mxbuild`:
  the reuse it bought applied to the one case tasks 6 to 8 do not have (the same graal commit
  twice), it cost ~3.5 min of save time per Windows run, and a key without `llvm_release` could
  serve a stale LLVM toolchain. A cold lean build - ~7.5 min on windows-amd64, ~5.5 min on
  linux-amd64, under 13 min end to end - is what the loop is built on. Evidence in the findings
  above.

- 2026-09-17: Exception handling via libunwind SEH mode + IR shim (spec section 2). Fallback: own SEH
  unwinder, triggered by the reviewer after two failed review cycles on Task 8.
- 2026-09-17: Windows uses a single LLVM batch (one object) instead of `ld -r`; code bounds come from
  COFF grouped sections `.text$svm0` / `.text$svm1` / `.text$svm2` (spec section 3).
- 2026-09-17: ~~The windows-x86_64 shadowed jars are referenced from suite.py by their GitHub release URL
  and sha512 directly (no lafo URL to rewrite). darwin-aarch64 only gets `moduleName` lines.~~
  **Superseded - see the stock-jars decision (2026-09-17, controller ruling, task 6) at the top of this
  section: suite.py points every platform, darwin-aarch64 included, at the stock `org.bytedeco` jars on
  Maven Central, and no shadowed jar of ours is referenced at all.**
- 2026-09-17: Triple for Java code: `x86_64-pc-windows-msvc` (LSDA confirmed in run
  https://github.com/Throwaway68/gha-graal/actions/runs/35207562231).
- 2026-09-17: libunwind is built for `x86_64-w64-windows-gnu` by `scripts/llvm/build-unwind-win.sh` against the
  MSYS2 UCRT headers, post-processed by `scripts/llvm/coff-assoc-comdats.py`, and installed as both
  `libunwind.a` and `unwind.lib` under `lib/x86_64-w64-windows-gnu`. Images link it together with
  `kernel32.lib`, `ntdll.lib` and `legacy_stdio_definitions.lib`.

- 2026-09-17 (task 8): **LLVM itself is patched for the Win64 home space, rather than working around it
  in the backend.** The spec provides for this ("llvm fork branch `graal/22.1.8-win`, only if LLVM
  itself needs a change"). `X86Subtarget::isCallingConvWin64` now answers `isTargetWin64()` for
  `CallingConv::GRAAL`, so the Graal convention on Windows is the Win64 convention with two reserved
  registers - which is what it is meant to be everywhere else. One `case` in a header, no effect off
  Windows (`isTargetWin64()` is false there). Published as `llvm-22.1.8-graal.3`; the alternative was a
  C-ABI thunk in front of every entry point, which needs the thunk to carry the method's symbol (the
  JNI function table reaches the stub through a `MethodPointer`, i.e. through
  `HostedMethod.getUniqueShortName()`), so the method's real code would have to be renamed and the code
  cache taught the new name - about sixty lines of naming contract, a permanent hole in the code range
  where the thunks live, and still wrong for anything else that assumes the platform ABI.

- 2026-09-17 (task 8): **the SEH glue lives in `.text$svm3`, not in `.text$svm1`** (the brief suggested
  the code section). `LLVMObjectFileReader.parseCode` takes the first section whose name *starts with*
  `.text$svm1` and every method offset is relative to that section's start, so anything else in it can
  only cost: at best it inflates the last method's size, at worst - if a pass ever reorders the module
  so that non-method code lands at offset 0 - it shifts `codeStart` against every recorded offset.
  `.text$svm3` sorts after the end marker, keeps plain `.text` free of it, and is still adjacent to the
  code. The shim is never a Java frame and nothing looks its address up.

- 2026-09-17 (task 8): **the JNI transition wrappers stay in plain `.text`, and `.text$svm2` keeps its
  `.p2align 4`** (both were carry-forward items from the task 7 review). The wrappers are `LinkOnce`,
  so moving them would put a second `.text$svm1`-named section in the object, exactly the ambiguity
  `parseCode` cannot afford; and nothing reads the end marker at run time, so making it exact buys
  nothing. Evidence for both in the findings above.

- 2026-09-17 (final review): **the spec's section 3 verification is done at build time, not at run
  time, and there is one object rather than a list.** The spec asks for the per-batch objects to be
  handed to the final image link as a list, and for a runtime check that every compiled method's
  address lies between `__svm_code_section` and `__svm_text_end`. Neither is what the implementation
  does. Windows compiles the whole image as a **single LLVM batch**, because the method offsets have
  to be known before the image is linked - a per-batch list cannot provide them, as each object's
  placement is only decided by the linker - and one object is what makes `parseCode`'s
  "offset within `.text$svm1`" contract hold. Placement is therefore verified at **build time**:
  `LLVMObjectFileReader.parseCode` reads every method's offset out of the first `.text$svm1` section
  and the first method sits at offset 0 (the `InvalidMethodPointerHandler` stub), backed by the
  offline `objdump`/`llvm-nm`/`llvm-readobj` evidence in the findings above (`.text$svm0` and
  `.text$svm2` empty and holding the two markers at offset 0, `.text$svm1` 0x266a6e bytes, the SEH
  glue in `.text$svm3`, the JNI wrappers in plain `.text`). **Nothing reads the markers at run time**
  - they exist only because `NativeImage.build` declares them undefined when the code cache does not
  define them - so a runtime bounds check would have had to be written for the occasion and would
  have tested the linker, not the image. Recorded as a deviation rather than a gap.


## Dead ends

- 2026-09-18 (task 1, spike run https://github.com/Throwaway68/gha-graal/actions/runs/35325048211):
  a throwaway `win-ssh-spike.yml` could not be dispatched at all -
  `gh workflow run` and the REST dispatch both answer `HTTP 404: workflow win-ssh-spike.yml not
  found on the default branch`, because `workflow_dispatch` only exists for workflows that are on
  the default branch. The spike ran on `on: push` to `round2-ssh` with a `paths:` filter instead,
  which is what a throwaway wants anyway: one push of the script = one iteration.
- 2026-09-18 (task 1, spike run https://github.com/Throwaway68/gha-graal/actions/runs/35325048211):
  the first `ssh -o ProxyCommand='cloudflared access tcp --hostname %h'` from
  the Mac died with `dial tcp: lookup <name>.trycloudflare.com: no such host` - not the tunnel's
  fault: the local resolver NXDOMAINs subdomains of `trycloudflare.com` (`dig @8.8.8.8` answers,
  the router does not), as several ISP resolvers now do. Worked around by running the client end in
  a container with its own resolver (`docker run -i --rm --dns 8.8.8.8 cloudflare/cloudflared access
  tcp --hostname %h` as the ProxyCommand); noted in the README.
