#!/usr/bin/env bash
# Release smoke test for the Native Image LLVM backend beyond hello world: build
# tests/programs/stress with the backend and check its output.
#
#   smoke-stress.sh <graalvm-home> <work-dir>
#
# `stress` exercises the parts of the runtime a hello world never touches:
# exceptions (deep throw/catch with a stack trace, implicit exceptions, rethrow
# and wrap, finally order), the garbage collector (collections through live
# frames, weak references, allocation pressure) and threads (start/join,
# synchronized, wait/notify, collections while threads run, an uncaught
# exception on a second thread). It prints one "OK <check>" line per check and
# "STRESS OK" at the end; dev-run.sh compares that against expected.txt and
# prints "DEV-RUN OK". This wrapper only pins down which program is run.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
bash "$here/dev-run.sh" "${1:?graalvm home}" "$here/../../tests/programs/stress" "${2:?work dir}"
