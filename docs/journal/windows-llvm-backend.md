# Windows LLVM backend journal

Working notes for porting the Native Image LLVM backend to windows-x86_64.
Spec: docs/superpowers/specs/2026-09-17-windows-llvm-backend-design.md.
Every entry is dated (YYYY-MM-DD) and names the commit or workflow run it comes from.

## Milestones

- (none yet)

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

## Decisions

- 2026-09-17: Exception handling via libunwind SEH mode + IR shim (spec section 2). Fallback: own SEH
  unwinder, triggered by the reviewer after two failed review cycles on Task 8.
- 2026-09-17: Windows uses a single LLVM batch (one object) instead of `ld -r`; code bounds come from
  COFF grouped sections `.text$svm0` / `.text$svm1` / `.text$svm2` (spec section 3).
- 2026-09-17: The windows-x86_64 shadowed jars are referenced from suite.py by their GitHub release URL
  and sha512 directly (no lafo URL to rewrite). darwin-aarch64 only gets `moduleName` lines.

## Dead ends

- (none yet)
