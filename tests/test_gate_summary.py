"""Unit tests for scripts/graalvm/gate-summary.py.

The main fixture is a verbatim 20-line excerpt of the first real gate log, run
https://github.com/Throwaway68/gha-graal/actions/runs/35346576305 (linux-amd64,
`build,helloworld,hellomodule` under `--tool:llvm-backend`): the whole BEGIN/END/ABORT
skeleton of that run plus the two kinds of noise that sit between those lines. It is the
run that showed `END:` is logged for a task that failed, so it is also the regression test
for blaming the last task that began when the gate aborts.
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("gate_summary", ROOT / "scripts" / "graalvm" / "gate-summary.py")
gate_summary = importlib.util.module_from_spec(SPEC)
sys.modules["gate_summary"] = gate_summary
SPEC.loader.exec_module(gate_summary)

RUN_35346576305 = """\
gate: 18 Sep 2026 12:48:51(+00:00) BEGIN: Gate
gate: 18 Sep 2026 12:48:51(+00:00) BEGIN: Versions
gate: 18 Sep 2026 12:48:51(+00:00) END:   Versions [0:00:00.213570] [disk (free/total): 83.6GB/145.2GB]
gate: 18 Sep 2026 12:48:51(+00:00) BEGIN: JDKReleaseInfo
gate: 18 Sep 2026 12:48:51(+00:00) END:   JDKReleaseInfo [0:00:00.000211] [disk (free/total): 83.6GB/145.2GB]
gate: 18 Sep 2026 12:48:51(+00:00) BEGIN: VerifyMultiReleaseProjects
gate: 18 Sep 2026 12:48:51(+00:00) END:   VerifyMultiReleaseProjects [0:00:00.016835] [disk (free/total): 83.6GB/145.2GB]
gate: 18 Sep 2026 12:48:51(+00:00) BEGIN: Clean
gate: 18 Sep 2026 12:48:51(+00:00) END:   Clean [0:00:00.058613] [disk (free/total): 83.6GB/145.2GB]
gate: 18 Sep 2026 12:48:51(+00:00) BEGIN: BuildWithJavac
gate: 18 Sep 2026 12:52:44(+03:53) END:   BuildWithJavac [0:03:52.741304] [disk (free/total): 72.8GB/145.2GB]
gate: 18 Sep 2026 12:52:44(+03:53) BEGIN: module build demo
Command '/home/runner/work/gha-graal/gha-graal/graal/sdk/mxbuild/linux-amd64/GRAALVM_41ABF4132D_JAVA25/graalvm-41abf4132d-java25-25.3.4.1-dev/bin/native-image @/tmp/ni_args_kxohl3ly.args' returned non-zero exit status 1.
gate: 18 Sep 2026 13:01:39(+12:48) END:   module build demo [0:08:55.555972] [disk (free/total): 72.7GB/145.2GB]
The sequence of mx commands that were executed until the failure follows:

mx --strict-compliance build -p --check-rebuild --warning-as-error --force-javac
mx --strict-compliance hellomodule -H:+UnlockExperimentalVMOptions --tool:llvm-backend -H:-UnlockExperimentalVMOptions -H:+UnlockExperimentalVMOptions -H:+RuntimeClassLoading -H:+AllowJRTFileSystem -H:-LegacyJavaOptionMode -H:-UnlockExperimentalVMOptions

If the previous sequence is incomplete or some commands were executed programmatically use:

mx --strict-compliance gate --strict-mode --tags build,helloworld,hellomodule '--extra-image-builder-arguments=-H:+UnlockExperimentalVMOptions --tool:llvm-backend -H:-UnlockExperimentalVMOptions'

gate: 18 Sep 2026 13:01:39(+12:48) ABORT: Gate [0:12:48.591203] [disk (free/total): 72.7GB/145.2GB]
"""

# windows-2022 has no os.statvfs, so mx logs no `[disk ...]` suffix there.
WINDOWS_PASS = """\
gate: 18 Sep 2026 14:00:00(+00:00) BEGIN: Gate
gate: 18 Sep 2026 14:00:00(+00:00) BEGIN: BuildWithJavac
gate: 18 Sep 2026 14:08:00(+08:00) END:   BuildWithJavac [0:08:00]
gate: 18 Sep 2026 14:08:00(+08:00) BEGIN: image demos
gate: 18 Sep 2026 14:30:00(+30:00) END:   image demos [0:22:00]
gate: 18 Sep 2026 14:30:00(+30:00) END:   Gate [0:30:00]
"""


def summarize(text):
    return gate_summary.report(*gate_summary.parse(text.splitlines(keepends=True)))


def test_failed_gate_blames_the_task_that_printed_END():
    assert summarize(RUN_35346576305) == '\n'.join([
        '  Versions                    ok       0:00:00.213570',
        '  JDKReleaseInfo              ok       0:00:00.000211',
        '  VerifyMultiReleaseProjects  ok       0:00:00.016835',
        '  Clean                       ok       0:00:00.058613',
        '  BuildWithJavac              ok       0:03:52.741304',
        '  module build demo           FAILED   0:08:55.555972',
        '  --------------------------  -------  -------',
        '  Gate                        FAILED   0:12:48.591203',
        'GATE FAILED: module build demo',
        'last mx command: mx --strict-compliance hellomodule -H:+UnlockExperimentalVMOptions '
        '--tool:llvm-backend -H:-UnlockExperimentalVMOptions -H:+UnlockExperimentalVMOptions '
        '-H:+RuntimeClassLoading -H:+AllowJRTFileSystem -H:-LegacyJavaOptionMode '
        '-H:-UnlockExperimentalVMOptions',
    ])


def test_passing_gate_without_disk_stats():
    assert summarize(WINDOWS_PASS) == '\n'.join([
        '  BuildWithJavac  ok       0:08:00',
        '  image demos     ok       0:22:00',
        '  --------------  -------  -------',
        '  Gate            ok       0:30:00',
        'GATE PASSED: BuildWithJavac, image demos',
    ])


def test_killed_job_leaves_the_running_task_visible():
    # The log of a job that hit its timeout: no ABORT, no END for the task or for the gate.
    killed = '\n'.join(WINDOWS_PASS.splitlines()[:4]) + '\n'
    assert summarize(killed).splitlines()[-1] == \
        'GATE INCOMPLETE: no task failed, but the gate did not finish either'
    assert '  image demos     RUNNING  -' in summarize(killed)


def test_empty_log():
    assert summarize('') == 'GATE FAILED: no gate task ran'
