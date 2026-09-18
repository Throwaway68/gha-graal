#!/usr/bin/env python3
"""Summarize an `mx gate` log: one line per gate task, then the verdict.

    python3 scripts/graalvm/gate-summary.py gate.log

`graalvm-gate.yml` runs this after the gate and uploads the output as `gate-summary.txt`, so
that reading a run does not mean scrolling a six-figure number of log lines.

The log lines it reads come from `Task._timestamp` / `Task.stop` / `Task.abort` in mx's
`src/mx/_impl/mx_gate.py` (mx 7.85.1):

    gate: 18 Sep 2026 10:11:22(+01:23) BEGIN: image demos
    gate: 18 Sep 2026 10:15:00(+05:01) END:   image demos [0:03:38] [disk (free/total): 12.3GB/80.0GB]
    gate: 18 Sep 2026 10:15:00(+05:01) ABORT: image demos [0:03:38]

(the `[disk ...]` suffix needs `os.statvfs`, so it is there on linux/macOS and not on Windows).
mx wraps the whole run in a task titled `Gate`, which is reported here as the total.

Deliberately driven by BEGIN/END/ABORT rather than by mx's own `Gate task times:` section at the
end: a gate that is killed - job timeout, a hung image build, a runner that went away - never
prints that section, and those are exactly the runs whose summary matters. A task that begins and
never ends is reported as `RUNNING`, which is that case.
"""
import re
import sys

# `.*?` rather than the exact timestamp: only the marker and what follows it are load-bearing.
TASK_LINE = re.compile(r'^gate: .*?\b(BEGIN|END|ABORT):\s+(\S.*)$')
DURATION = re.compile(r'\s+\[(\d+:\d\d:\d\d(?:\.\d+)?)\]$')
TOTAL_TITLE = 'Gate'


def parse(lines):
    """-> (list of (title, status, duration), (status, duration) of the total or None)."""
    tasks, index, total = [], {}, None
    for line in lines:
        m = TASK_LINE.match(line.rstrip('\r\n'))
        if not m:
            continue
        marker, rest = m.group(1), m.group(2)
        disk = rest.find(' [disk ')
        if disk != -1:
            rest = rest[:disk]
        d = DURATION.search(rest)
        title, duration = (rest[:d.start()], d.group(1)) if d else (rest, '-')
        if marker == 'BEGIN':
            # A repeated title (the `build` tag is re-run by `mx gate --partial`) overwrites the
            # earlier entry's slot, so its END lands on the entry its BEGIN opened.
            index[title] = len(tasks)
            tasks.append([title, 'RUNNING', '-'])
        elif title in index:
            tasks[index[title]][1:] = ['ok' if marker == 'END' else 'FAILED', duration]
    for i in range(len(tasks) - 1, -1, -1):
        if tasks[i][0] == TOTAL_TITLE:
            total = tuple(tasks.pop(i)[1:])
            break
    return [tuple(t) for t in tasks], total


def report(tasks, total):
    out = []
    width = max([len(t[0]) for t in tasks] + [len(TOTAL_TITLE)])
    for title, status, duration in tasks:
        out.append(f'  {title:<{width}}  {status:<7}  {duration}')
    if total:
        out.append(f'  {"-" * width}  {"-" * 7}  {"-" * 7}')
        out.append(f'  {TOTAL_TITLE:<{width}}  {total[0]:<7}  {total[1]}')
    bad = [t[0] for t in tasks if t[1] != 'ok']
    if bad:
        out.append('GATE FAILED: ' + ', '.join(bad))
    elif not tasks:
        out.append('GATE FAILED: no gate task ran')
    elif not total or total[0] != 'ok':
        # Every task passed but the gate itself did not finish: mx aborted outside a task (a
        # `--tags` typo, --strict-mode refusing a missing tool) or the job was killed.
        out.append('GATE INCOMPLETE: every task that started passed, but the gate did not finish')
    else:
        out.append('GATE PASSED: ' + ', '.join(t[0] for t in tasks))
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
