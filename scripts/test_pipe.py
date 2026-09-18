#!/usr/bin/env python3
"""Self-check for pipe.py.   Run:  python3 scripts/test_pipe.py

Asserts only, no framework on purpose. Covers the runId scoping the dashboard's feed
filtering depends on, and the updatedAt freshness its staleness warning depends on.
"""
import argparse, glob, json, os, re, subprocess, sys, tempfile

PIPE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pipe.py")

# Section 9's reference table, verbatim: every spec path these buses have ever loaded.
SECTION_9_SLUGS = [
    ("crm/docs/superpowers/specs/2026-07-14-calculator-improvements-design.md", "calculator-improvements"),
    ("crm/specs/008-broadcast-groups/design.md", "008-broadcast-groups"),
    ("crm/specs/009-messaging-hub/design.md", "009-messaging-hub"),
    ("crm/specs/010-portfolio-review/design.md", "010-portfolio-review"),
    ("docs/ipo-mandate-automation-spec.md", "ipo-mandate-automation"),
    ("docs/superpowers/specs/2026-07-27-client-investment-horizon.md", "client-investment-horizon"),
    ("docs/superpowers/specs/2026-07-27-google-contacts-sync-design.md", "google-contacts-sync"),
]


def run(root, *args, env=None, expect=0):
    r = subprocess.run([sys.executable, PIPE, "--root", root, *args],
                       capture_output=True, text=True, encoding="utf-8",
                       env={**os.environ, **env} if env else None)
    assert r.returncode == expect, \
        f"{' '.join(args)} exited {r.returncode}, expected {expect}:\n{r.stdout}{r.stderr}"
    return r.stdout + r.stderr


def git(repo, *args):
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True,
                       encoding="utf-8")
    assert r.returncode == 0, f"git {' '.join(args)} in {repo}:\n{r.stderr}"
    return r.stdout


def git_repo(path, base, content="base\n"):
    """A real one-commit repo - worktree add and finish shell out to git for real."""
    os.makedirs(path, exist_ok=True)
    git(path, "init", "-q", "-b", base)
    git(path, "config", "user.email", "team@example.com")
    git(path, "config", "user.name", "team")
    write(os.path.join(path, "README.md"), content)
    git(path, "add", "-A")
    git(path, "commit", "-qm", "base commit")
    return path


def write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def import_pipe():
    """pipe.py as a module, for the pure helpers and the parser walk."""
    sys.path.insert(0, os.path.dirname(PIPE))
    import pipe
    return pipe


def events(root):
    with open(os.path.join(root, "messages.jsonl"), encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def read_run(root):
    with open(os.path.join(root, "run.json"), encoding="utf-8") as f:
        return json.load(f)


def command_drift_check():
    """Every `pipe.py <cmd>` an agent is told to run must exist in the parser.

    The files below are instructions that get executed - agent definitions, skills and
    the runbook. Spec and ADR docs are deliberately excluded: they name commands that
    are designed but not built yet, which is not drift. This is a superset guard: it
    passes whether one command is named or twelve, so it never constrains what a later
    per-role cheatsheet says."""
    parser = import_pipe().build_parser()
    real = {name for a in parser._actions if isinstance(a, argparse._SubParsersAction)
            for name in a.choices}
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    docs = (glob.glob(os.path.join(repo, "agents", "*.md"))
            + glob.glob(os.path.join(repo, "skills", "**", "SKILL.md"), recursive=True)
            + [os.path.join(repo, "docs", "orchestration-runbook.md")])
    assert len(docs) > 5, f"found almost no agent files - the guard would pass vacuously: {docs}"
    for path in docs:
        with open(path, encoding="utf-8") as f:
            text = f.read()
        for cmd in re.findall(r"(?:pipe\.py|\$PIPE)\s+([a-z][a-z-]*)", text):
            assert cmd in real, \
                f"{os.path.relpath(path, repo)} tells an agent to run `pipe.py {cmd}`, " \
                f"which pipe.py's parser does not have. Known: {', '.join(sorted(real))}"


def workstream_checks():
    """The git-backed half: worktree add and finish over real temporary repos.

    Its own temp dir with ignore_cleanup_errors because git marks objects under .git
    read-only and Windows then refuses to delete them - cleanup noise, not a failure."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        repos = os.path.join(tmp, "repos")
        api = git_repo(os.path.join(repos, "api"), "develop")
        web = git_repo(os.path.join(repos, "web"), "master")
        root = os.path.join(tmp, "bus", "pipeline")
        run(root, "init", "--feature", "Messaging hub", "--slug", "messaging-hub")

        # --- one workstream, one branch name, in every repository it touches --------
        run(root, "worktree", "add", "--service", "api", "--repo", api)
        run(root, "worktree", "add", "--service", "web", "--repo", web)
        r = read_run(root)
        assert r["branch"] == "feature/messaging-hub", r["branch"]
        assert [e["branch"] for e in r["repos"]] == [r["branch"]] * 2, \
            "every repo must carry the one branch name fixed at init"
        assert [e["base"] for e in r["repos"]] == ["develop", "master"], \
            "base is recorded per repo at creation - it is not always master"
        for e in r["repos"]:
            assert os.path.isdir(e["worktree"]), e
            assert os.path.basename(os.path.dirname(e["worktree"])) == "wt-messaging-hub", e

        # --- no later step can even ask for a second branch name -------------------
        run(root, "worktree", "add", "--service", "api", "--repo", api,
            "--branch", "feature/other", expect=2)

        # --- a bare finish plans, changes nothing, and flags an empty branch --------
        heads = {p: git(p, "rev-parse", "HEAD") for p in (api, web)}
        out = run(root, "finish")
        assert "NO COMMITS" in out, f"a branch nobody committed to is a red flag:\n{out}"
        assert {p: git(p, "rev-parse", "HEAD") for p in (api, web)} == heads, \
            "a bare finish must not move any HEAD"
        assert os.path.isfile(os.path.join(root, "run.json")), "a bare finish must not archive the bus"

        # the coder's work: commits on the workstream branch, inside the worktrees
        wt_api, wt_web = [e["worktree"] for e in read_run(root)["repos"]]
        write(os.path.join(wt_api, "api.txt"), "api work\n")
        git(wt_api, "add", "-A"); git(wt_api, "commit", "-qm", "T1: api work")
        write(os.path.join(wt_web, "README.md"), "web work\n")
        git(wt_web, "add", "-A"); git(wt_web, "commit", "-qm", "T2: web work")

        # --- one conflicting repo means nothing merges anywhere ---------------------
        write(os.path.join(web, "README.md"), "meanwhile, on master\n")
        git(web, "commit", "-qam", "base moved under us")
        before = git(api, "rev-parse", "HEAD")
        out = run(root, "finish", "--apply", expect=1)
        assert "README.md" in out and "NOTHING" in out, out
        assert git(api, "rev-parse", "HEAD") == before, \
            "a conflict in one repo must leave every other repo unmerged"

        # --- apply merges every repo, archives the bus, and KEEPS the worktrees -----
        git(web, "reset", "-q", "--hard", "HEAD~1")
        run(root, "finish", "--apply")
        assert git(api, "rev-parse", "HEAD") != before, "apply must merge a clean repo"
        assert "api.txt" in git(api, "show", "--name-only", "--format=", "HEAD^2")
        for wt in (wt_api, wt_web):
            assert os.path.exists(os.path.join(wt, ".git")), \
                f"closing a run must not remove the worktree a later wave stands on: {wt}"
        archived = [d for d in os.listdir(tmp) if d.startswith("messaging-hub.closed-")]
        assert archived and not os.path.exists(root), f"bus should be archived: {archived}"

        # --- tearing the container down is the separate, explicit act ---------------
        billing = git_repo(os.path.join(repos, "billing"), "main")
        b_root = os.path.join(tmp, "bus2", "pipeline")
        run(b_root, "init", "--feature", "Billing fix", "--slug", "billing-fix")
        run(b_root, "worktree", "add", "--service", "billing", "--repo", billing)
        b_wt = read_run(b_root)["repos"][0]["worktree"]
        write(os.path.join(b_wt, "x.txt"), "x\n")
        git(b_wt, "add", "-A"); git(b_wt, "commit", "-qm", "T1: x")
        run(b_root, "finish", "--teardown", expect=1)   # refused: it would change disk
        run(b_root, "finish", "--apply", "--teardown")
        assert not os.path.exists(b_wt) and not os.path.exists(os.path.dirname(b_wt)), \
            "--teardown removes the worktree and the container"


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

        # --- the slug rule is code, so every wave re-derives the SAME name ----------
        pipe = import_pipe()
        for path, expected in SECTION_9_SLUGS:
            assert pipe.derive_slug(path) == expected, \
                f"{path} -> {pipe.derive_slug(path)}, expected {expected}"
        assert pipe.derive_slug("docs\\specs\\009-messaging-hub\\design.md") == "009-messaging-hub", \
            "a Windows path must derive the same slug as its POSIX spelling"
        assert len(pipe.derive_slug("docs/" + "x" * 80 + ".md")) <= 40, "slug caps at 40"

        # --- a slug is never silently reused while its workstream is active ---------
        home = os.path.join(tmp, "aohome")
        env = {"AGENT_ORCHESTRATION_HOME": home}
        assert run(root, "slug", "--spec", "docs/widgets-spec.md", env=env).strip() == "widgets"
        busy = os.path.join(home, "pipelines", "widgets", "pipeline")
        run(busy, "init", "--feature", "widgets")
        assert run(root, "slug", "--spec", "docs/widgets-spec.md", env=env).strip() == "widgets-2", \
            "an active workstream's slug must be suffixed, never reused"
        run(busy, "set-status", "done")
        assert run(root, "slug", "--title", "Widgets!", env=env).strip() == "widgets", \
            "a closed workstream releases its slug"

        # --- init without --slug is byte-for-byte the legacy bus at <cwd>/pipeline ---
        legacy = os.path.join(tmp, "legacy")
        os.makedirs(legacy)
        r = subprocess.run([sys.executable, PIPE, "init", "--feature", "legacy feature"],
                           cwd=legacy, capture_output=True, text=True, encoding="utf-8")
        assert r.returncode == 0, r.stderr
        with open(os.path.join(legacy, "pipeline", "run.json"), encoding="utf-8") as f:
            lrun = json.load(f)
        assert not {"slug", "branch", "repos", "mode"} & set(lrun), \
            f"a no-slug init must stay today's run.json exactly: {sorted(lrun)}"

        # --- init --slug fixes the branch and relocates the bus under the fixed root -
        r = subprocess.run([sys.executable, PIPE, "init", "--feature", "Hub",
                            "--slug", "messaging-hub"], cwd=legacy, capture_output=True,
                           text=True, encoding="utf-8", env={**os.environ, **env})
        assert r.returncode == 0, r.stderr
        bus = r.stdout.strip().splitlines()[-1]
        assert bus == os.path.join(home, "pipelines", "messaging-hub", "pipeline"), bus
        srun = read_run(bus)
        assert srun["slug"] == "messaging-hub" and srun["branch"] == "feature/messaging-hub" \
            and srun["repos"] == [] and srun["mode"] == "worktree", srun

        # --- a malformed review is rejected, not half-written -----------------------
        bad = os.path.join(tmp, "bad.json")
        write(bad, json.dumps({"recommendation": "approve",
                               "findings": [{"severity": "critical", "note": "boom"}]}))
        run(root, "review", "--from", bad, expect=1)
        for f in ("review.json", "review.md"):
            assert not os.path.exists(os.path.join(root, "review", f)), \
                f"{f} must not exist - validation runs before anything is opened"

        # --- a valid review lands as both artifacts and emits its own finding -------
        good = os.path.join(tmp, "good.json")
        write(good, json.dumps({
            "recommendation": "changes-required", "summary": "one blocker",
            "findings": [{"severity": "blocking", "file": "src/a.py", "line": 4,
                          "note": "unguarded write", "planRef": "T2"},
                         {"severity": "nit", "note": "typo"}]}))
        assert "1 blocking" in run(root, "review", "--from", good)
        with open(os.path.join(root, "review", "review.md"), encoding="utf-8") as f:
            md = f.read()
        assert "### blocking (1)" in md and "unguarded write" in md \
            and "## Recommendation" in md, md
        with open(os.path.join(root, "review", "review.json"), encoding="utf-8") as f:
            assert json.load(f)["findings"][0]["planRef"] == "T2"
        last = events(root)[-1]
        assert last["agent"] == "reviewer" and last["type"] == "finding", last
        run(root, "review", "--from", good, "--service", "svcA")
        assert os.path.isfile(os.path.join(root, "services", "svcA", "review", "review.json")), \
            "--service writes into the per-service namespace"

        # --- the QA gate is an exit code: one failing gate at a time ----------------
        qa = os.path.join(tmp, "qa", "pipeline")
        run(qa, "init", "--feature", "gate check")
        results = os.path.join(qa, "test", "results.json")
        write(results, json.dumps({"iteration": 1, "passed": 3, "failed": 0}))
        run(qa, "task", "add", "--id", "T1", "--title", "x")
        run(qa, "task", "update", "--id", "T1", "--status", "done")
        clean = os.path.join(tmp, "clean-review.json")
        write(clean, json.dumps({"recommendation": "approve", "findings": []}))
        run(qa, "review", "--from", clean)
        assert "green" in run(qa, "qa-check"), "a green bus must pass the gate"

        run(qa, "review", "--from", good)          # one blocking finding
        assert "blocking" in run(qa, "qa-check", expect=1)
        run(qa, "review", "--from", clean)         # re-review clears it, no lifecycle

        run(qa, "task", "update", "--id", "T1", "--status", "todo")
        assert "T1" in run(qa, "qa-check", expect=1)
        run(qa, "task", "update", "--id", "T1", "--status", "done")

        write(results, json.dumps({"iteration": 2, "passed": 1, "failed": 2}))
        assert "failing test" in run(qa, "qa-check", expect=1)
        os.remove(results)
        assert "results.json" in run(qa, "qa-check", expect=1), \
            "absent results are not green - the tester simply never reported"

    workstream_checks()
    command_drift_check()
    print("ok - pipe.py self-check passed")


if __name__ == "__main__":
    main()
