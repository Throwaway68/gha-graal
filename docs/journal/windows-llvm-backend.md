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
  archive as `unwind.lib`, and `include/unwind.h`, and nothing loose at its root. This is the release
  tasks 5 to 9 consume.

- 2026-09-17: Shadowed jars release `jars-1.5.7-graal.1`
  (run https://github.com/Throwaway68/gha-graal/actions/runs/35215356056, green first try):
  `javacpp-shadowed-1.5.7-graal.1-windows-x86_64.jar`,
  `llvm-shadowed-13.0.1-1.5.7-graal.1-windows-x86_64.jar` and `manifest.json`, built by
  `.github/workflows/jars.yml` from the Maven Central windows-x86_64 platform jars with
  `scripts/jars/shadow.py`. Task 6 points suite.py's windows-amd64
  `JAVACPP_PLATFORM_SPECIFIC_SHADOWED` / `LLVM_PLATFORM_SPECIFIC_SHADOWED` at them.

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
- 2026-09-17 (research): `CallingConv::GRAAL` (107) on Win64 lowers arguments with `CC_X86_Win64_C`
  and allocates no 32-byte shadow area (`isCallingConvWin64` is false for it). Consistent on both sides
  of Java-to-Java calls; C-ABI calls use the normal Win64 convention. Verified empirically in Task 8.
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

- 2026-09-17 (run https://github.com/Throwaway68/gha-graal/actions/runs/35215356056): **the windows-x86_64
  shadowed jars, for Task 6 to paste into suite.py verbatim** (sizes 1338481 and 620008997 bytes; digests
  re-verified after downloading the published assets):
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
  is a jar to publish rather than a source change; this branch therefore keeps
  `llvm_supported = not (mx.is_darwin() and mx.get_arch() == "aarch64")` and leaves the two
  darwin/aarch64 suite.py entries byte-identical to upstream. With that, darwin-aarch64 is back to
  the pristine tag's behaviour: the GraalVM builds and `dev-run` stops at
  `Error: Unknown name in option specification: tool:llvm-backend` (exit 20), the same way the tag
  behaves on Windows.

- 2026-09-17 (the user's tip): GitHub Actions runners can be reached over **ssh for interactive
  debugging** (a tmate/upterm-style step), which beats a full workflow round trip per attempt when
  the same 10-minute Windows job is being poked at repeatedly. `graalvm-dev.yml` now has an opt-in
  `debug_ssh` input (default off) that runs `mxschmitt/action-tmate@v3.24` after `dev-run`,
  whether or not it failed, with `limit-access-to-actor: true` - this repository is public and the
  connection string lands in the log, so the dispatching account needs a public key at
  https://github.com/settings/keys for the session to be usable.

## Decisions

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
- 2026-09-17: The windows-x86_64 shadowed jars are referenced from suite.py by their GitHub release URL
  and sha512 directly (no lafo URL to rewrite). darwin-aarch64 only gets `moduleName` lines.
- 2026-09-17: Triple for Java code: `x86_64-pc-windows-msvc` (LSDA confirmed in run
  https://github.com/Throwaway68/gha-graal/actions/runs/35207562231).
- 2026-09-17: libunwind is built for `x86_64-w64-windows-gnu` by `scripts/llvm/build-unwind-win.sh` against the
  MSYS2 UCRT headers, post-processed by `scripts/llvm/coff-assoc-comdats.py`, and installed as both
  `libunwind.a` and `unwind.lib` under `lib/x86_64-w64-windows-gnu`. Images link it together with
  `kernel32.lib`, `ntdll.lib` and `legacy_stdio_definitions.lib`.

## Dead ends

- (none yet)
