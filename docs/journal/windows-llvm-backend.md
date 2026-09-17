# Windows LLVM backend journal

Working notes for porting the Native Image LLVM backend to windows-x86_64.
Spec: docs/superpowers/specs/2026-09-17-windows-llvm-backend-design.md.
Every entry is dated (YYYY-MM-DD) and names the commit or workflow run it comes from.

## Milestones

- 2026-09-17: Windows exception-handling spike green on windows-2022 (steps 1-4 of the plan's Task 2):
  https://github.com/Throwaway68/gha-graal/actions/runs/35207963198, re-run green after the review fixes
  (hard step-1 assertions, strict COFF rewriter):
  https://github.com/Throwaway68/gha-graal/actions/runs/35209025076
- 2026-09-17: LLVM release `llvm-22.1.8-graal.2` with Windows libunwind, all three platforms green on the
  first try (run https://github.com/Throwaway68/gha-graal/actions/runs/35209720023). Seven assets as in
  graal.1; `llvm-22.1.8-graal.2-windows-amd64.tar.gz` carries `lib/x86_64-w64-windows-gnu/libunwind.a`,
  the same archive as `unwind.lib`, and `include/unwind.h`. This is the release tasks 5 to 9 consume.

## Findings

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
  `__imp___acrt_iob_func`, `abort`, `fflush`, `fprintf`, `memcpy`). Cosmetic: the script's three diagnostic
  symbol lists (`libunwind-defined.txt`, `libunwind-undefined{,-raw}.txt`) land next to `bin/`, `lib/`, `include/`
  at the bundle root; harmless, and worth moving to the build dir if a later release wants a clean root.

## Decisions

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
