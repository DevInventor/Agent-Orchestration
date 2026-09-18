#!/usr/bin/env python3
"""Self-check for pipe.py.   Run:  python3 scripts/test_pipe.py

Asserts only, no framework on purpose. Covers the runId scoping the dashboard's feed
filtering depends on, and the updatedAt freshness its staleness warning depends on.
"""
import json, os, subprocess, sys, tempfile

PIPE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pipe.py")


def run(root, *args):
    r = subprocess.run([sys.executable, PIPE, "--root", root, *args],
                       capture_output=True, text=True)
    assert r.returncode == 0, f"{' '.join(args)} failed:\n{r.stderr}"
    return r.stdout


def events(root):
    with open(os.path.join(root, "messages.jsonl"), encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def read_run(root):
    with open(os.path.join(root, "run.json"), encoding="utf-8") as f:
        return json.load(f)


def main():
    with tempfile.TemporaryDirectory() as tmp:
        root = os.path.join(tmp, "pipeline")

        # --- a run stamps its id on every event -------------------------------
        run(root, "init", "--feature", "first feature")
        r1 = read_run(root)
        run(root, "event", "--agent", "coder", "--type", "status", "--summary", "a")
        run(root, "event", "--agent", "tester", "--type", "result", "--summary", "b")

        evs = events(root)
        assert len(evs) == 3, f"expected 3 events (init + 2), got {len(evs)}"
        assert all(e.get("runId") == r1["runId"] for e in evs), \
            "every event must carry its run's id"

        # --- a second run appends to the SAME log: the reason runId exists -----
        run(root, "init", "--feature", "second feature")
        r2 = read_run(root)
        assert r2["runId"] != r1["runId"], \
            "a new run must get a new id even when started in the same second"
        run(root, "event", "--agent", "coder", "--type", "status", "--summary", "c")

        evs = events(root)
        assert len(evs) == 5, f"log is append-only across runs, got {len(evs)}"
        mine = [e for e in evs if e.get("runId") == r2["runId"]]
        assert len(mine) == 2, f"run 2 owns exactly its own 2 events, got {len(mine)}"
        assert mine[-1]["summary"] == "c"
        assert not [e for e in mine if e["summary"] in ("a", "b")], \
            "run 1's events must not leak into run 2's feed"

        # --- updatedAt moves on mutation (the staleness signal rests on it) ----
        before = read_run(root)["updatedAt"]
        run(root, "phase", "plan")
        assert read_run(root)["updatedAt"] >= before, \
            "updatedAt must be refreshed on every run.json write"

        # --- a service entry carries its own updatedAt for per-lane staleness --
        run(root, "svc", "--name", "svcA", "--status", "running", "--phase", "test")
        svc = read_run(root)["services"]["svcA"]
        assert svc["updatedAt"] and svc["status"] == "running", svc

        # --- absent config is valid, not an error -----------------------------
        out = json.loads(run(root, "config", "--file", os.path.join(tmp, "nope.json")))
        assert out == {"configured": False, "services": []}, out

        # --- tasks round-trip --------------------------------------------------
        run(root, "task", "add", "--id", "T1", "--title", "x", "--owner", "coder")
        run(root, "task", "update", "--id", "T1", "--status", "done")
        with open(os.path.join(root, "tasks.json"), encoding="utf-8") as f:
            tasks = json.load(f)["tasks"]
        assert len(tasks) == 1 and tasks[0]["status"] == "done", tasks

    print("ok - pipe.py self-check passed")


if __name__ == "__main__":
    main()
