; Probe: does LLVM emit an Itanium LSDA into .xdata for the MSVC triple when the
; personality is a custom (non-MSVC, non-GCC) function, the way Native Image's
; Java personality will be? Compiled by .github/workflows/spike-win-eh.yml.
target triple = "x86_64-pc-windows-msvc"

declare i32 @__svm_seh_personality(ptr, ptr, ptr, ptr)
declare void @may_throw()
declare void @handler_called()

define i32 @probe() personality ptr @__svm_seh_personality {
entry:
  invoke void @may_throw() to label %ok unwind label %lp
ok:
  ret i32 0
lp:
  %lpad = landingpad { ptr, i32 } catch ptr null
  call void @handler_called()
  ret i32 1
}
