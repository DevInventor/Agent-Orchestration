#!/usr/bin/env python3
"""Run a long command without the agent watchdog killing the agent.

An agent dies after ~600s of silent output. A ten-minute `mvn test` or `pytest` is
silent for its whole duration, so the normal shape of a test phase kills the agent
running it. Five agents across two estates have died this way. Emitting status events
"as you go" cannot help: nothing can emit while the build holds the process.

    python3 scripts/heartbeat.py -- mvn -q test
    python3 scripts/heartbeat.py --lock jvm -- ./gradlew build

Prints a tick at least every 30s while the command lives, and exits with the command's
own exit code. --lock serialises heavy builds against each other: the runbook tells the
orchestrator to spawn a whole batch concurrently, which is right for coordination and
wrong for three JVM builds on one box.
"""
import argparse
import os
import subprocess
import sys
import time

TICK = 30
LOCKDIR = os.path.join(os.path.expanduser("~"), ".agent-orchestration", "locks")


def alive(pid):
    """Is that pid still running? Age alone is not enough: a hard kill never runs a
    shell trap, so a killed agent leaves its lock held, and an age-only break makes the
    next build wait out the full timeout for a process that died an hour ago."""
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                             capture_output=True, text=True).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def acquire(name):
    """Hold `name` until this process exits. Returns the lock path, or None if unlocked."""
    os.makedirs(LOCKDIR, exist_ok=True)
    path = os.path.join(LOCKDIR, name + ".lock")
    while True:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return path
        except FileExistsError:
            try:
                owner = int(open(path, encoding="utf-8").read().strip() or 0)
            except (ValueError, OSError):
                owner = 0
            if owner and alive(owner):
                print(f"[heartbeat] waiting on {name}, held by pid {owner}", flush=True)
                time.sleep(5)
                continue
            # ponytail: last writer wins on the steal. Two agents stealing the same dead
            # lock in the same instant both proceed; the cost is the contention this
            # script exists to avoid, not corruption. Add an atomic take-over if it bites.
            print(f"[heartbeat] breaking {name}: owner {owner or '?'} is gone", flush=True)
            try:
                os.unlink(path)
            except OSError:
                pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lock", help="serialise against other runs using this name")
    ap.add_argument("--tick", type=int, default=TICK)
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    a = ap.parse_args()
    cmd = a.cmd[1:] if a.cmd[:1] == ["--"] else a.cmd
    if not cmd:
        sys.exit("usage: heartbeat.py [--lock NAME] -- <command>")

    lock = acquire(a.lock) if a.lock else None
    started = time.time()
    try:
        # stdio is inherited, so the build's own output still streams through and the
        # ticks interleave with it. Nothing is buffered or swallowed.
        p = subprocess.Popen(cmd)
        while True:
            try:
                return p.wait(timeout=a.tick)
            except subprocess.TimeoutExpired:
                print(f"[heartbeat] {int(time.time() - started)}s, still running: "
                      f"{' '.join(cmd)}", flush=True)
    finally:
        if lock:
            try:
                os.unlink(lock)
            except OSError:
                pass


if __name__ == "__main__":
    sys.exit(main())
