#!/usr/bin/env bash
# Release smoke test for the Native Image LLVM backend beyond hello world: build
# tests/programs/{stress,complex,export} with the backend and check their output.
#
#   smoke-stress.sh <graalvm-home> <work-dir>
#
# Each program gets its own work directory under <work-dir> and is built and run by
# dev-run.sh, which compares the image's stdout against the program's expected.txt and
# prints "DEV-RUN OK". This wrapper only pins down which programs a release runs.
#
#   stress   the parts of the runtime a hello world never touches: exceptions (deep
#            throw/catch with a stack trace, implicit exceptions, rethrow and wrap,
#            finally order), the garbage collector (collections through live frames,
#            weak references, allocation pressure) and threads (start/join,
#            synchronized, wait/notify, collections while threads run, an uncaught
#            exception on a second thread). Ends with "STRESS OK".
#   complex  JNI in both directions against a shared library the *bundled* clang builds
#            on the runner: downcalls, upcalls, an upcall whose Java side throws, a
#            ThrowNew caught in Java, a @CEntryPoint entered from C through a function
#            pointer, the same traffic from six threads, plus ordinary library code
#            (collections, streams, records, regex, reflection, file IO). "COMPLEX OK".
#   export   the linker side: C resolving the image's own @CEntryPoint by the *symbol*
#            the annotation names (GetProcAddress on Windows, dlsym elsewhere), which
#            needs the image's export table. "EXPORT OK".
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
progs=$here/../../tests/programs
H=${1:?graalvm home}
W=${2:?work dir}
bash "$here/dev-run.sh" "$H" "$progs/stress"  "$W/stress"
bash "$here/dev-run.sh" "$H" "$progs/complex" "$W/complex"
bash "$here/dev-run.sh" "$H" "$progs/export"  "$W/export"
