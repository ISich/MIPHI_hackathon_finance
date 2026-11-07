"""Execution containment supervisor (Linux).

    python -I -m dd_backend.supervisor <worker_pid> <marker_path> -- <child argv...>

* Becomes a child subreaper (PR_SET_CHILD_SUBREAPER): every descendant of the execution that gets
  orphaned -- including ones that called setsid() or dropped their environment -- is re-parented
  to this process, so the whole execution tree stays visible as our descendants.
* Asks for SIGTERM when the worker dies (PR_SET_PDEATHSIG); SIGTERM/SIGINT/SIGHUP from the worker
  (timeout, shutdown) mean the same thing: stop the execution.
* When the child exits or a stop is requested, SIGKILLs all descendants, reaps them, verifies that
  none is left and only then writes ``marker_path`` ("contained"). No marker => containment was
  not verified, and the worker/recovery fail closed.
* Exit code: the child's exit code; 128+N if it died from signal N; 137 if stopped by request.

Not a security sandbox: a process can still double-fork *and* ptrace/escape via other means it has
rights to. It bounds the ordinary process tree of an execution.
"""
from __future__ import annotations

import ctypes
import os
import signal
import sys
import time
from pathlib import Path

PR_SET_PDEATHSIG = 1
PR_SET_CHILD_SUBREAPER = 36


def descendants(root: int) -> list[int]:
    """All live descendants of ``root`` by parent links (zombies included until reaped)."""
    children: dict[int, list[int]] = {}
    for entry in os.scandir("/proc"):
        if not entry.name.isdigit():
            continue
        try:
            ppid = int(Path(entry.path, "stat").read_text().rsplit(")", 1)[1].split()[1])
        except (OSError, IndexError, ValueError):
            continue
        children.setdefault(ppid, []).append(int(entry.name))
    out, stack = [], [root]
    while stack:
        for kid in children.get(stack.pop(), []):
            out.append(kid)
            stack.append(kid)
    return out


def contain(rounds: int = 500) -> bool:
    """Kill and reap every descendant; True only when no descendant remains."""
    me = os.getpid()
    for _ in range(rounds):
        for pid in descendants(me):
            try:
                os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
        while True:
            try:
                pid, _ = os.waitpid(-1, os.WNOHANG)
            except ChildProcessError:
                return not descendants(me)
            if pid == 0:
                break
        time.sleep(0.02)
    return False


def main() -> int:
    worker_pid, marker = int(sys.argv[1]), Path(sys.argv[2])
    cmd = sys.argv[4:]
    libc = ctypes.CDLL("libc.so.6", use_errno=True)
    if libc.prctl(PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) != 0:
        return 70  # cannot contain: refuse to run anything (no marker)
    libc.prctl(PR_SET_PDEATHSIG, signal.SIGTERM, 0, 0, 0)
    stop = {"flag": False}

    def request_stop(*_):
        stop["flag"] = True
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, request_stop)
    rc: int | None = None
    if os.getppid() == worker_pid:  # worker may have died before PDEATHSIG was armed
        # Handshake: publish our identity BEFORE any child exists. Recovery treats a present
        # ".started" without ".contained" as "must be verified" (fail closed), so there is no window
        # in which an execution runs while nobody knows which process contains it.
        started = marker.with_name(marker.name.replace(".contained", ".started"))
        me = os.getpid()
        start_ticks = Path(f"/proc/{me}/stat").read_text().rsplit(")", 1)[1].split()[19]
        tmp = started.with_name(started.name + ".tmp")
        tmp.write_text(f"{me} {start_ticks}\n")
        os.replace(tmp, started)
        child = os.fork()
        if child == 0:
            try:
                signal.signal(signal.SIGTERM, signal.SIG_DFL)
                signal.signal(signal.SIGINT, signal.SIG_DFL)
                signal.signal(signal.SIGHUP, signal.SIG_DFL)
                os.execv(cmd[0], cmd)
            finally:
                os._exit(127)
        while rc is None and not stop["flag"]:
            try:
                pid, status = os.waitpid(-1, os.WNOHANG)
            except ChildProcessError:
                break
            if pid == child:
                code = os.waitstatus_to_exitcode(status)
                rc = code if code >= 0 else 128 - code
            elif pid == 0:
                time.sleep(0.05)
    if contain():
        tmp = marker.with_name(marker.name + ".tmp")
        tmp.write_text("contained\n")
        os.replace(tmp, marker)
    return 137 if rc is None else rc


if __name__ == "__main__":
    sys.exit(main())
