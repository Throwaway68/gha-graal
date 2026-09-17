/* Probe: can a program built by cl.exe against the MSVC CRT call into libunwind
 * built in SEH mode for the mingw target?  Walks cl-compiled frames with
 * _Unwind_Backtrace and catches the SEH exception _Unwind_RaiseException raises.
 * Declarations are local so that the test does not depend on libunwind's headers
 * being usable from MSVC. Compiled by .github/workflows/spike-win-eh.yml. */
#include <stdio.h>
#include <stdint.h>
#include <windows.h>

#define URC_NO_REASON    0
#define URC_END_OF_STACK 5
#define STATUS_GCC_THROW 0x20474343

typedef int _Unwind_Reason_Code;
struct _Unwind_Context;
struct _Unwind_Exception {
    uint64_t exception_class;
    void (*exception_cleanup)(int, struct _Unwind_Exception *);
    uintptr_t private_[6];  /* SEH mode: 6 words, not the 2 of the Itanium ABI */
};
typedef _Unwind_Reason_Code (*_Unwind_Trace_Fn)(struct _Unwind_Context *, void *);
_Unwind_Reason_Code _Unwind_Backtrace(_Unwind_Trace_Fn, void *);
_Unwind_Reason_Code _Unwind_RaiseException(struct _Unwind_Exception *);
uintptr_t _Unwind_GetIP(struct _Unwind_Context *);

static int frames;

static _Unwind_Reason_Code trace(struct _Unwind_Context *ctx, void *arg) {
    (void)arg;
    frames++;
    printf("  frame %d ip=%p\n", frames, (void *)_Unwind_GetIP(ctx));
    return frames > 40 ? URC_END_OF_STACK : URC_NO_REASON;
}

__declspec(noinline) static int nested(int depth) {
    if (depth == 0) {
        frames = 0;
        _Unwind_Backtrace(trace, NULL);
        return frames;
    }
    return nested(depth - 1) + 1;
}

int main(void) {
    int n = nested(5);
    printf("backtrace frames=%d\n", n);
    if (n < 6) {
        printf("FAIL: expected at least 6 frames\n");
        return 2;
    }
    {
        struct _Unwind_Exception exc = {0};
        exc.exception_class = 0x4A41564100000000ull;  /* "JAVA" */
        __try {
            _Unwind_RaiseException(&exc);
            printf("FAIL: _Unwind_RaiseException returned\n");
            return 3;
        } __except (GetExceptionCode() == STATUS_GCC_THROW
                        ? EXCEPTION_EXECUTE_HANDLER : EXCEPTION_CONTINUE_SEARCH) {
            printf("caught STATUS_GCC_THROW\n");
        }
    }
    printf("SPIKE OK\n");
    return 0;
}
