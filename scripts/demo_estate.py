#!/usr/bin/env python3
"""Stand up (or tear down) a demo estate so the dashboard can be shown to a team.

Five workstreams covering every state the hall and the board can render: a run mid
fix-loop with tasks in all six columns, one waiting at a gate, one implementing, one gone
quiet, and one finished. Everything is built through pipe.py, so this is real bus state
rather than a mock the dashboard is pretending to read - the only direct writes are the
things no command exposes (a backdated updatedAt for staleness, per-service test counts,
and repos[]).

    python3 scripts/demo_estate.py          # build it
    python3 scripts/demo_estate.py --down   # remove it

Every slug is prefixed `demo-`, and --down deletes exactly those. Nothing else is touched.
"""
import argparse, json, os, shutil, subprocess, sys, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
PIPE = os.path.join(HERE, "pipe.py")
ROOT = os.path.join(os.path.expanduser("~"), ".agent-orchestration", "pipelines")
PREFIX = "demo-"


def run(root, *args):
    r = subprocess.run([sys.executable, PIPE, "--root", root, *args],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode:
        sys.exit(f"pipe.py {' '.join(args)} failed:\n{r.stdout}{r.stderr}")
    return r.stdout


def bus(slug):
    return os.path.join(ROOT, slug, "pipeline")


def patch_run(slug, **fields):
    p = os.path.join(bus(slug), "run.json")
    d = json.load(open(p, encoding="utf-8"))
    d.update(fields)
    json.dump(d, open(p, "w", encoding="utf-8"), indent=2)


def ago(minutes):
    t = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=minutes)
    return t.isoformat(timespec="seconds")


# slug, feature, repos, and the tasks that give each column something to hold
ESTATE = [
    dict(
        slug="demo-auth-v2",
        feature="Rotate refresh tokens and share one session contract",
        repos=["OpenCRM", "SpiceTrade"],
        phase="test", agent="tester", status="running", loop=(2, 5),
        services={"OpenCRM": {"passed": 18, "failed": 1}, "SpiceTrade": {"passed": 9, "failed": 0}},
        criteria=["AC1 - Refresh tokens rotate on every use",
                  "AC2 - Sessions share one contract across services",
                  "AC3 - Logout revokes all active sessions",
                  "AC4 - Every session change is auditable"],
        tasks=[
            ("T1", "Normalize token claim names", "OpenCRM", "coder", "done", ["AC1"]),
            ("T2", "Drop legacy claim aliases", "OpenCRM", "coder", "done", ["AC1"]),
            ("T3", "Rotate refresh token on reuse", "OpenCRM", "tester", "qa", ["AC1"]),
            ("T4", "Shared session contract types", "SpiceTrade", "reviewer", "review", ["AC2"]),
            ("T5", "Revoke-on-logout endpoint", "OpenCRM", "coder", "ready", ["AC3"]),
            ("T6", "Session store migration to the shared schema", "SpiceTrade", "coder",
             "in_progress", ["AC2"]),
            ("T7", "Propagate session id into the audit log", "SpiceTrade", "coder",
             "todo", ["AC4"]),
        ],
        events=[("orchestrator", "status", "Plan finalized by user"),
                ("orchestrator", "status", "Worktrees created for 2 services"),
                ("coder", "handoff", "Implemented 6/6 tasks"),
                ("tester", "result", "Tests 17/19 passed (iter 1) - 2 negative paths"),
                ("coder", "handoff", "Fixed 1 issue, ready for re-test"),
                ("tester", "result", "Tests 18/19 passed (iter 2)")],
    ),
    dict(
        slug="demo-billing-webhooks",
        feature="Retry, verify and dead-letter billing webhooks",
        repos=["OpenCRM"],
        phase="plan", agent="planner", status="awaiting_approval", loop=(0, 5),
        criteria=["AC1 - Failed deliveries retry with backoff",
                  "AC2 - Signature verified before any side effect",
                  "AC3 - Replays are idempotent"],
        tasks=[("T1", "Verify webhook signature before dispatch", "OpenCRM", "coder", "todo", ["AC2"]),
               ("T2", "Retry queue with exponential backoff", "OpenCRM", "coder", "todo", ["AC1"]),
               ("T3", "Idempotency key on delivery attempts", "OpenCRM", "coder", "todo", ["AC3"]),
               ("T4", "Dead-letter listing endpoint", "OpenCRM", "coder", "todo", ["AC1"])],
        events=[("planner", "handoff", "Plan ready: 4 tasks, 1 service, 3 criteria"),
                ("orchestrator", "question", "Plan ready - reply finalize to start, or edit scope")],
    ),
    dict(
        slug="demo-search-reindex",
        feature="Reindex search without downtime",
        repos=["SpiceTrade", "OpenCRM", "Deployment"],
        phase="implement", agent="coder", status="running", loop=(1, 5),
        criteria=["AC1 - Reindex runs without downtime",
                  "AC2 - Schema changes roll forward safely"],
        tasks=[("T1", "Reindex job status table", "SpiceTrade", "coder", "done", ["AC1"]),
               ("T2", "Versioned index schema writer", "SpiceTrade", "coder", "in_progress", ["AC2"]),
               ("T3", "Document mapper for the new schema", "OpenCRM", "coder", "in_progress", ["AC2"]),
               ("T4", "Blue/green index alias cutover", "Deployment", "coder", "todo", ["AC1"])],
        events=[("orchestrator", "status", "Wave 1 admitted: SpiceTrade, OpenCRM"),
                ("coder", "status", "Implemented 3/5 tasks - SpiceTrade")],
    ),
    dict(
        slug="demo-stepup-fallback",
        feature="Fall back to a link when step-up times out",
        repos=["GT-Janus", "GTID-Vault"],
        phase="review", agent="reviewer", status="running", loop=(1, 5),
        stale_minutes=390,          # past the 3-minute rule by a wide margin
        services={"GT-Janus": {"passed": 24, "failed": 0}},
        criteria=["AC1 - The step-up holds for 65 seconds",
                  "AC2 - The link is single-use and expires"],
        tasks=[("T1", "Hold the step-up for 65 seconds", "GT-Janus", "coder", "done", ["AC1"]),
               ("T2", "Fallback link issued on timeout", "GTID-Vault", "coder", "done", ["AC1"]),
               ("T3", "Link is single-use and expires", "GT-Janus", "reviewer", "review", ["AC2"])],
        events=[("tester", "result", "Tests 24/24 passed (iter 1)"),
                ("reviewer", "status", "Reading the blast radius")],
    ),
    dict(
        slug="demo-ipo-mandate",
        feature="Automate the IPO mandate hand-off",
        repos=["OpenCRM"],
        phase="done", agent="reviewer", status="done", loop=(1, 5),
        services={"OpenCRM": {"passed": 31, "failed": 0}},
        criteria=["AC1 - Mandates are filed without a manual step"],
        tasks=[("T1", "Mandate intake endpoint", "OpenCRM", "coder", "done", ["AC1"]),
               ("T2", "Filing job with retries", "OpenCRM", "coder", "done", ["AC1"])],
        events=[("reviewer", "finding", "Review: 0 blocking, 2 notes"),
                ("orchestrator", "status", "qa-check green - merged and archived")],
    ),
]


def build():
    made = []
    for w in ESTATE:
        slug, root = w["slug"], bus(w["slug"])
        if os.path.isdir(os.path.dirname(root)):
            shutil.rmtree(os.path.dirname(root))
        run(root, "init", "--slug", slug, "--feature", w["feature"])

        for a, kind, summary in w["events"]:
            run(root, "event", "--agent", a, "--type", kind, "--summary", summary)

        for tid, title, svc, owner, status, _ in w["tasks"]:
            run(root, "task", "add", "--id", tid, "--title", title,
                "--service", svc, "--owner", owner)
            if status != "todo":
                run(root, "task", "update", "--id", tid, "--status", status)

        run(root, "phase", w["phase"])
        run(root, "agent", w["agent"])
        run(root, "loop", "--count", str(w["loop"][0]), "--max", str(w["loop"][1]))
        run(root, "set-status", w["status"])

        # plan.json carries the criteria the board's right-hand column reads, and the
        # criteriaRef the task cards badge themselves with.
        json.dump({
            "approach": "Demo estate - not a real run.",
            "services": [{"name": s, "dependsOnServices": []} for s in w["repos"]],
            "acceptanceCriteria": w["criteria"],
            "tasks": [{"id": t[0], "title": t[1], "service": t[2], "criteriaRef": t[5]}
                      for t in w["tasks"]],
        }, open(os.path.join(root, "plan.json"), "w", encoding="utf-8"), indent=2)

        # What no command exposes: the workstream's repos, per-service test counts, and a
        # backdated updatedAt - staleness is measured, so it cannot be asked for.
        extra = {"repos": [{"service": s, "repo": s, "worktree": s, "branch": "feature/" + slug,
                            "base": "master"} for s in w["repos"]]}
        if w.get("services"):
            extra["services"] = w["services"]
        if w.get("stale_minutes"):
            extra["updatedAt"] = ago(w["stale_minutes"])
        patch_run(slug, **extra)
        made.append(slug)
    return made


def teardown():
    gone = []
    for name in sorted(os.listdir(ROOT)) if os.path.isdir(ROOT) else []:
        if name.startswith(PREFIX):
            shutil.rmtree(os.path.join(ROOT, name))
            gone.append(name)
    return gone


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--down", action="store_true", help="remove the demo estate")
    a = ap.parse_args()
    if a.down:
        gone = teardown()
        print("removed:", ", ".join(gone) or "nothing")
    else:
        made = build()
        print("built under", ROOT)
        for s in made:
            print("  ", s)
        print("\nOpen the hall, then click any card to open its board.")
