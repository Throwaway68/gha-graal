#!/usr/bin/env python3
"""Summarize an `mx gate` log: one line per gate task, then the verdict.

    python3 scripts/graalvm/gate-summary.py gate.log

`graalvm-gate.yml` runs this after the gate and uploads the output as `gate-summary.txt`, so
that reading a run does not mean scrolling a five-figure number of log lines.

The lines it reads come from `Task._timestamp` / `Task.stop` / `Task.abort` in mx's
`src/mx/_impl/mx_gate.py` (mx 7.85.1):

    gate: 18 Sep 2026 12:52:44(+03:53) BEGIN: module build demo
    gate: 18 Sep 2026 13:01:39(+12:48) END:   module build demo [0:08:55.555972] [disk (free/total): 72.7GB/145.2GB]
    gate: 18 Sep 2026 13:01:39(+12:48) ABORT: Gate [0:12:48.591203] [disk (free/total): 72.7GB/145.2GB]

(the `[disk ...]` suffix needs `os.statvfs`, so it is there on linux/macOS and not on Windows).

**`END:` does not mean the task passed.** `Task.__exit__` calls `stop()` - which logs `END:` -
while the exception that killed the task is still propagating; only the outermost task, titled
`Gate`, gets an `ABORT:` line (`total.abort(...)` in `mx_gate.gate`). Verified on run
35346576305, where `module build demo` printed `END:` and the gate failed inside it. So the rule
here is: if the gate aborted, the task that failed is the last one that began, and the ones
before it passed. That rule also attributes an abort *between* two tasks - a `--tags` typo,
`--strict-mode` refusing a tool, a suite runner that throws outside a `with Task(...)` - to the last
task that began, which is then blamed for something it did not do; the `last mx command:` line and
the log itself say which it was.

Deliberately driven by BEGIN/END/ABORT rather than by mx's own `Gate task times:` section: a gate
that is killed - job timeout, a hung image build, a runner that went away - never prints that
section, and those are exactly the runs whose summary matters.
"""
import re
import sys

# `.*?` rather than the exact timestamp: only the marker and what follows it are load-bearing.
TASK_LINE = re.compile(r'^gate: .*?\b(BEGIN|END|ABORT):\s+(\S.*)$')
DURATION = re.compile(r'\s+\[(\d+:\d\d:\d\d(?:\.\d+)?)\]$')
TOTAL_TITLE = 'Gate'
# mx prints the commands it ran before the failure, then the same list's "use this to repeat the
# whole gate" line; only the first block says which image build actually failed.
CMDS_BEGIN = 'The sequence of mx commands that were executed until the failure follows:'
CMDS_END = 'If the previous sequence is incomplete'


def parse(lines):
    """-> (tasks, total, last mx command) with tasks/total as [title, status, duration]."""
    tasks, index, total, in_cmds, command = [], {}, None, False, None
    for line in lines:
        line = line.rstrip('\r\n')
        if line.startswith(CMDS_BEGIN):
            in_cmds = True
        elif line.startswith(CMDS_END):
            in_cmds = False
        elif in_cmds and line.startswith('mx '):
            command = line
        m = TASK_LINE.match(line)
        if not m:
            continue
        marker, rest = m.group(1), m.group(2)
        disk = rest.find(' [disk ')
        if disk != -1:
            rest = rest[:disk]
        d = DURATION.search(rest)
        title, duration = (rest[:d.start()], d.group(1)) if d else (rest, '-')
        if marker == 'BEGIN':
            # A repeated title (`mx gate --partial` re-runs the build tasks) takes over the slot,
            # so its END lands on the entry its own BEGIN opened.
            index[title] = len(tasks)
            tasks.append([title, 'RUNNING', '-'])
        elif title in index:
            tasks[index[title]][1:] = ['ok' if marker == 'END' else 'FAILED', duration]
    for i in range(len(tasks) - 1, -1, -1):
        if tasks[i][0] == TOTAL_TITLE:
            total = tasks.pop(i)
            break
    if total and total[1] == 'FAILED' and tasks:
        tasks[-1][1] = 'FAILED'   # see the module docstring: END: is logged for a failed task too
    return tasks, total, command


def report(tasks, total, command):
    out, width = [], max([len(t[0]) for t in tasks] + [len(TOTAL_TITLE)])
    for title, status, duration in tasks:
        out.append(f'  {title:<{width}}  {status:<7}  {duration}')
    if total:
        out.append(f'  {"-" * width}  {"-" * 7}  {"-" * 7}')
        out.append(f'  {TOTAL_TITLE:<{width}}  {total[1]:<7}  {total[2]}')
    failed = [t[0] for t in tasks if t[1] == 'FAILED']
    if failed:
        out.append('GATE FAILED: ' + ', '.join(failed))
    elif not tasks:
        out.append('GATE FAILED: no gate task ran')
    elif not total or total[1] != 'ok':
        # The gate aborted outside any task, or the log stops in the middle of one: a `--tags`
        # typo, --strict-mode refusing a missing tool, a killed job.
        out.append('GATE INCOMPLETE: no task failed, but the gate did not finish either')
    else:
        out.append('GATE PASSED: ' + ', '.join(t[0] for t in tasks))
    if command:
        out.append('last mx command: ' + command)
    return '\n'.join(out)


def main(argv):
    if len(argv) != 2:
        sys.exit(f'usage: {argv[0]} <gate.log>')
    try:
        with open(argv[1], encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
    except OSError as e:
        # `if: always()` means this also runs when the gate step never produced a log.
        print(f'GATE FAILED: no gate log ({e})')
        return 0
    print(report(*parse(lines)))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
