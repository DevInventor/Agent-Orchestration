#!/usr/bin/env python3
"""Self-check for pipe.py.   Run:  python3 scripts/test_pipe.py

Asserts only, no framework on purpose. Covers the runId scoping the dashboard's feed
filtering depends on, and the updatedAt freshness its staleness warning depends on.
"""
import argparse, glob, json, os, re, shutil, socket, subprocess, sys, tempfile, time
import urllib.error, urllib.request

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


def run(root, *args, env=None, expect=0, cwd=None):
    r = subprocess.run([sys.executable, PIPE, "--root", root, *args],
                       capture_output=True, text=True, encoding="utf-8", cwd=cwd,
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


def read_json(path, default=None):
    if not os.path.isfile(path):
        return {} if default is None else default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def command_drift_check(repo=None):
    """Every `pipe.py <cmd>` an agent is told to run must exist in the parser.

    The files below are instructions that get executed - agent definitions, skills and
    the runbook. Spec and ADR docs are deliberately excluded: they name commands that
    are designed but not built yet, which is not drift. This is a superset guard: it
    passes whether one command is named or twelve, so it never constrains what a later
    per-role cheatsheet says.

    `repo` defaults to this checkout; passing one lets the guard be pointed at a
    throwaway tree, which is how S24 proves the guard can actually fail."""
    parser = import_pipe().build_parser()
    real = {name for a in parser._actions if isinstance(a, argparse._SubParsersAction)
            for name in a.choices}
    repo = repo or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    docs = (glob.glob(os.path.join(repo, "agents", "*.md"))
            + glob.glob(os.path.join(repo, "skills", "**", "SKILL.md"), recursive=True)
            + [p for p in [os.path.join(repo, "docs", "orchestration-runbook.md")]
               if os.path.isfile(p)]
            + glob.glob(os.path.join(repo, "docs", "runbook", "*.md")))
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


def core_checks():
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
        # init's stdout is ONE JSON document (S25); the bus path travels in busPath,
        # not as a trailing bare line. Read the key, never the last line.
        bus = json.loads(r.stdout)["busPath"]
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


# --------------------------------------------------------------------------------
# Scenario suite (pipeline/test/scenarios.json). One function per scenario, run
# through the table at the bottom so one failure never hides the ones after it.
# --------------------------------------------------------------------------------

def workstream(tmp, slug, services):
    """A bus plus one real git repo per (service, base) - the shape every git-backed
    scenario needs: slug -> branch -> repos[]. Returns the bus root."""
    root = os.path.join(tmp, "bus", "pipeline")
    run(root, "init", "--feature", slug, "--slug", slug)
    for svc, base in services:
        repo = git_repo(os.path.join(tmp, "repos", svc), base)
        run(root, "worktree", "add", "--service", svc, "--repo", repo)
    return root


def commit_work(root):
    """The coder's half of the contract: a commit per service on the one branch."""
    for e in read_run(root)["repos"]:
        write(os.path.join(e["worktree"], e["service"] + ".txt"), "work\n")
        git(e["worktree"], "add", "-A")
        git(e["worktree"], "commit", "-qm", f"T1: {e['service']} work")


def heads(entries, ref="HEAD"):
    return {e["repo"]: git(e["repo"], "rev-parse", ref).strip() for e in entries}


def merge_lands_on_each_repos_own_base():
    """S1 - the whole chain: one slug names one branch, every repo records it, and
    finish merges THAT branch into THAT repo's own recorded base. A wrong-branch or
    wrong-base merge here is the most expensive silent failure this feature can have."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        root = workstream(tmp, "messaging-hub", [("api", "develop"), ("web", "master")])
        commit_work(root)
        repos = read_run(root)["repos"]
        branch = read_run(root)["branch"]
        assert branch == "feature/messaging-hub", branch
        before = {e["repo"]: git(e["repo"], "rev-parse", e["base"]).strip() for e in repos}
        tips = {e["repo"]: git(e["repo"], "rev-parse", e["branch"]).strip() for e in repos}
        run(root, "finish", "--apply")
        for e in repos:
            base_now = git(e["repo"], "rev-parse", e["base"]).strip()
            assert base_now != before[e["repo"]], \
                f"{e['service']}: {e['base']} did not advance - nothing was merged home"
            parents = git(e["repo"], "rev-list", "--parents", "-n", "1", base_now).split()
            assert len(parents) == 3, \
                f"{e['service']}: expected a --no-ff merge commit with 2 parents, got {parents}"
            assert parents[1] == before[e["repo"]], \
                f"{e['service']}: merge's first parent is not the recorded base's old tip"
            assert parents[2] == tips[e["repo"]], \
                f"{e['service']}: merged {parents[2]} instead of {e['branch']} ({tips[e['repo']]})"
            assert git(e["repo"], "rev-parse", "--abbrev-ref", "HEAD").strip() == e["base"], \
                f"{e['service']}: HEAD left on a branch other than its recorded base"


def wave_two_reattaches_to_the_one_branch():
    """S3 - a workstream outlives its runs: re-adding a service must attach to the
    branch wave 1 created, not invent a second name or lose wave 1's commits."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        root = workstream(tmp, "wave", [("svc", "main")])
        commit_work(root)
        e1 = read_run(root)["repos"][0]
        wave1 = git(e1["repo"], "rev-parse", e1["branch"]).strip()
        git(e1["repo"], "worktree", "remove", "--force", e1["worktree"])
        run(root, "worktree", "add", "--service", "svc", "--repo", e1["repo"])
        e2 = read_run(root)["repos"][0]
        assert len(read_run(root)["repos"]) == 1, "a re-add must replace the entry, not duplicate it"
        assert (e2["branch"], e2["base"], e2["worktree"]) == (e1["branch"], e1["base"], e1["worktree"]), \
            f"wave 2 changed the workstream's identity: {e1} -> {e2}"
        assert git(e1["repo"], "rev-parse", e2["branch"]).strip() == wave1, \
            "wave 2 re-pointed the branch and dropped wave 1's commits"


def init_refuses_a_non_slug_identity():
    """S4 - the branch name is fixed at init, so an identity no repo can accept has to
    be refused there. `feature/Messaging Hub` is not a legal git ref."""
    with tempfile.TemporaryDirectory() as tmp:
        root = os.path.join(tmp, "pipeline")
        r = subprocess.run([sys.executable, PIPE, "--root", root, "init",
                            "--feature", "Messaging hub", "--slug", "Messaging Hub"],
                           capture_output=True, text=True, encoding="utf-8")
        assert r.returncode != 0, (
            "init accepted --slug 'Messaging Hub' and recorded branch "
            f"{read_json(os.path.join(root, 'run.json')).get('branch')!r}, which git cannot "
            "create - the workstream is only discovered to be unusable at `worktree add`")


def teardown_removes_every_container():
    """S7 - services in separate repos (the primary case, spec section 3) put their
    containers under different repos roots. Teardown must remove all of them."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        root = os.path.join(tmp, "bus", "pipeline")
        run(root, "init", "--feature", "Split", "--slug", "split")
        for svc, base, where in (("api", "develop", "rootA"), ("web", "master", "rootB")):
            repo = git_repo(os.path.join(tmp, where, svc), base)
            run(root, "worktree", "add", "--service", svc, "--repo", repo)
        commit_work(root)
        repos = read_run(root)["repos"]
        containers = sorted({os.path.dirname(e["worktree"]) for e in repos})
        assert len(containers) == 2, containers
        run(root, "finish", "--apply", "--teardown")
        left = [c for c in containers if os.path.exists(c)]
        assert not left, \
            f"--teardown left {len(left)} of {len(containers)} containers behind: {left} - " \
            "it removes only the container of repos[0]"


def apply_refuses_a_repo_off_its_base():
    """S11 - `git merge` merges into whatever HEAD is. A repo parked on another branch
    must block the whole apply, not silently take the merge onto that branch."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        root = workstream(tmp, "offbase", [("api", "develop"), ("web", "master")])
        commit_work(root)
        repos = read_run(root)["repos"]
        web = [e for e in repos if e["service"] == "web"][0]
        git(web["repo"], "switch", "-q", "-c", "hotfix")
        before = heads(repos)
        out = run(root, "finish", "--apply", expect=1)
        assert "web" in out and web["base"] in out, f"the offending repo must be named:\n{out}"
        assert heads(repos) == before, "a repo off its base must stop every merge, not just its own"
        assert git(web["repo"], "rev-parse", "--abbrev-ref", "HEAD").strip() == "hotfix", \
            "apply must not switch branches under the user"


def apply_refuses_a_dirty_working_tree():
    """S12 - an all-or-nothing merge cannot be all-or-nothing if one repo's merge can
    fail on local edits after another repo has already merged."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        root = workstream(tmp, "dirty", [("api", "develop"), ("web", "master")])
        commit_work(root)
        repos = read_run(root)["repos"]
        web = [e for e in repos if e["service"] == "web"][0]
        write(os.path.join(web["repo"], "scratch.txt"), "uncommitted\n")
        before = heads(repos)
        out = run(root, "finish", "--apply", expect=1)
        assert "uncommitted" in out.lower(), out
        assert heads(repos) == before, "nothing may merge while any repo is dirty"


def finish_reports_a_missing_repo_loudly():
    """S13 - spec section 17: a bus can outlive the repo it points at. The plan must
    say so rather than merge what is left."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        root = workstream(tmp, "gone", [("api", "develop"), ("web", "master")])
        commit_work(root)
        run_json = os.path.join(root, "run.json")
        data = read_json(run_json)
        missing = os.path.join(tmp, "repos", "moved-away")
        survivor = [e for e in data["repos"] if e["service"] == "api"][0]
        before = git(survivor["repo"], "rev-parse", survivor["base"]).strip()
        for e in data["repos"]:
            if e["service"] == "web":
                e["repo"] = missing
        write(run_json, json.dumps(data, indent=2))
        out = run(root, "finish", expect=1)
        assert "moved-away" in out, f"the missing repo must be named:\n{out}"
        assert git(survivor["repo"], "rev-parse", survivor["base"]).strip() == before


def slug_rule_edges():
    """S15 - the rule has to be predictable enough to guess the branch name, on the
    spellings a Windows session actually produces."""
    pipe = import_pipe()
    cases = [
        ("crm/specs/009-messaging-hub/", "009-messaging-hub"),     # trailing separator
        ("crm\\specs\\009-messaging-hub\\design.md", "009-messaging-hub"),
        ("docs/Spec.MD", "docs"),                                   # generic check is case-blind
        ("docs/specs/2026-07-27-thing/design.md", "thing"),         # date stripped off the parent
    ]
    for path, expected in cases:
        assert pipe.derive_slug(path) == expected, \
            f"{path!r} -> {pipe.derive_slug(path)!r}, expected {expected!r}"
    capped = pipe.derive_slug("docs/" + "word-" * 20 + ".md")
    assert len(capped) <= 40 and not capped.endswith("-"), capped
    with tempfile.TemporaryDirectory() as tmp:
        root = os.path.join(tmp, "pipeline")
        run(root, "init", "--feature", "f")
        env = {"AGENT_ORCHESTRATION_HOME": os.path.join(tmp, "aohome")}
        assert run(root, "slug", "--title", "Add SSO logout endpoint!", env=env).strip() \
            == "add-sso-logout-endpoint", "/ship has no doc - it slugifies the title"


def review_rejections_never_touch_disk():
    """S18 - every malformed shape is rejected before anything is opened for writing,
    and a review that was already good survives the attempt."""
    with tempfile.TemporaryDirectory() as tmp:
        root = os.path.join(tmp, "pipeline")
        run(root, "init", "--feature", "review gate")
        good = os.path.join(tmp, "good.json")
        write(good, json.dumps({"recommendation": "approve", "summary": "fine", "findings": []}))
        run(root, "review", "--from", good)
        rj = os.path.join(root, "review", "review.json")
        rm = os.path.join(root, "review", "review.md")
        before = (open(rj, encoding="utf-8").read(), open(rm, encoding="utf-8").read())
        bad = {
            "bad-severity": {"recommendation": "approve",
                             "findings": [{"severity": "critical", "note": "boom"}]},
            "bad-recommendation": {"recommendation": "lgtm", "findings": []},
            "empty-note": {"recommendation": "approve",
                           "findings": [{"severity": "major", "note": "   "}]},
            "findings-not-a-list": {"recommendation": "approve", "findings": {"severity": "major"}},
            "not-an-object": ["nope"],
        }
        for name, payload in bad.items():
            p = os.path.join(tmp, name + ".json")
            write(p, json.dumps(payload))
            out = run(root, "review", "--from", p, expect=1)
            assert "review:" in out, f"{name}: the reviewer needs to know what to fix:\n{out}"
        trunc = os.path.join(tmp, "truncated.json")
        write(trunc, '{"recommendation":')
        run(root, "review", "--from", trunc, expect=1)
        run(root, "review", "--from", os.path.join(tmp, "absent.json"), expect=1)
        after = (open(rj, encoding="utf-8").read(), open(rm, encoding="utf-8").read())
        assert after == before, "a rejected payload must not disturb the review already on the bus"


def agent_file(name):
    """An agent definition's text and its frontmatter `tools:` allowlist."""
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    text = open(os.path.join(repo, "agents", name + ".md"), encoding="utf-8").read()
    tools = [l for l in text.splitlines() if l.startswith("tools:")]
    assert len(tools) == 1, f"{name}.md must carry exactly one tools: line: {tools}"
    return text, {t.strip() for t in tools[0].split(":", 1)[1].split(",")}


def reviewer_holds_no_write_tool():
    """S19 - AC7 names the tool grant explicitly; it is the permission boundary."""
    text, granted = agent_file("reviewer")
    assert "Bash" in granted, f"the reviewer needs Bash to call pipe.py: {granted}"
    assert not granted & {"Write", "Edit"}, f"the reviewer must hold no Write/Edit: {granted}"
    assert re.search(r"(pipe\.py|\$PIPE)\s+review\s+--from", text), \
        "reviewer.md must tell the reviewer how it persists findings"


def the_operator_is_gated_and_reports_evidence():
    """S44 - AC9. An operator without a gate is an agent that deploys ungated, which is
    the single property section 12 exists to prevent; and its report shape is fixed at
    four fields because a verdict is exactly what it must not return. S23 then proves
    every pipe.py command this file names actually exists."""
    text, granted = agent_file("operator")
    assert "Bash" in granted, f"the operator needs Bash to run the thing: {granted}"
    assert not granted & {"Write", "Edit"}, \
        f"the operator must hold no Write/Edit (ADR-0001's precedent): {granted}"
    assert re.search(r"(pipe\.py|\$PIPE)\s+wait\s+--for\s+gate", text), \
        "operator.md must wait at the gate before touching a shared environment"
    for field in ("command", "exit code", "what changed", "what to verify"):
        assert field in text, f"operator.md must name the report field {field!r}"


def the_planner_is_granted_the_graph_it_is_told_to_query():
    """S45 - AC11. `tools:` is an allowlist and a wrong MCP prefix grants nothing
    silently: the planner just falls back to crawling, which looks like success. So
    assert the exact ids, and that the prose names the four queries section 11 asks for.
    Grep stays granted - coverage is best-effort and it is the fallback."""
    text, granted = agent_file("planner")
    prefix = "mcp__codebase-memory-mcp__"
    for tool in ("get_architecture", "search_graph", "trace_path", "get_code_snippet",
                 "index_status", "list_projects", "check_index_coverage"):
        assert prefix + tool in granted, \
            f"planner.md must grant {prefix + tool} verbatim; granted: {sorted(granted)}"
        assert tool in text, f"planner.md grants {tool} but never tells the planner to use it"
    assert {"Grep", "Glob"} <= granted, f"the Glob/Grep fallback must stay granted: {granted}"
    assert not re.search(r"Index the codebase", text), \
        "planner.md still tells the planner to crawl the codebase"


def every_agent_carries_a_bounded_cheatsheet():
    """S46 - AC10(a). 62% of a spawn's preamble was the protocol document and a coder
    uses four commands, so each role carries its own block instead. The ceiling is the
    point: unbounded, a cheatsheet grows back into the protocol it replaced. S23 proves
    the commands these blocks name exist; this proves they stay small."""
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    roles = ["planner", "coder", "tester", "reviewer", "operator"]
    for name in [r + ".md" for r in roles]:      # team-rules.md is shared prose, not a role
        path = os.path.join(repo, "agents", name)
        assert os.path.isfile(path), f"agents/{name} is missing"
        text = open(path, encoding="utf-8").read()
        block = re.search(r"^## Commands\b.*?```bash\n(.*?)```", text, re.S | re.M)
        assert block, f"{name} carries no `## Commands` cheatsheet"
        size = len(block.group(1).encode("utf-8"))
        assert 0 < size <= 600, f"{name}'s cheatsheet is {size} B; the ceiling is 600"
        assert not re.search(r"Read the \*\*pipeline-protocol\*\* skill", text), \
            f"{name} still orders a full read of the protocol document"


def qa_check_spans_service_namespaces():
    """S22 - a green service must not hide a blocked one; --service scopes the gate."""
    with tempfile.TemporaryDirectory() as tmp:
        root = os.path.join(tmp, "pipeline")
        run(root, "init", "--feature", "multi")
        run(root, "task", "add", "--id", "T1", "--title", "x")
        run(root, "task", "update", "--id", "T1", "--status", "done")
        clean = os.path.join(tmp, "clean.json")
        write(clean, json.dumps({"recommendation": "approve", "findings": []}))
        for svc in ("api", "web"):
            run(root, "svc", "--name", svc, "--status", "running")
            os.makedirs(os.path.join(root, "services", svc, "test"), exist_ok=True)
            write(os.path.join(root, "services", svc, "test", "results.json"),
                  json.dumps({"iteration": 1, "passed": 2, "failed": 0}))
            run(root, "review", "--from", clean, "--service", svc)
        assert "green" in run(root, "qa-check")
        blocker = os.path.join(tmp, "blocker.json")
        write(blocker, json.dumps({"recommendation": "changes-required",
                                   "findings": [{"severity": "blocking", "file": "src/w.py",
                                                 "note": "unclosed session"}]}))
        run(root, "review", "--from", blocker, "--service", "web")
        out = run(root, "qa-check", expect=1)
        assert "services/web/review/review.json" in out.replace("\\", "/"), \
            f"the gate must name what and where:\n{out}"
        assert "green" in run(root, "qa-check", "--service", "api"), \
            "--service scopes the gate to one lane"


def drift_guard_catches_an_unknown_command():
    """S24 - AC10 is 'a test FAILS if...'. Point the guard at a throwaway doc tree that
    names a command pipe.py does not have and assert it actually raises."""
    with tempfile.TemporaryDirectory() as tmp:
        agents = os.path.join(tmp, "agents")
        os.makedirs(agents)
        for i in range(6):
            write(os.path.join(agents, f"a{i}.md"), "Run `$PIPE status` when done.\n")
        command_drift_check(tmp)          # a clean tree passes
        write(os.path.join(agents, "a3.md"),
              "Cheatsheet\n\n- `$PIPE teleport --to qa` when the tests are green\n")
        try:
            command_drift_check(tmp)
        except AssertionError as e:
            assert "teleport" in str(e) and "a3.md" in str(e), \
                f"the failure must name the file and the command: {e}"
        else:
            raise AssertionError("the drift guard passed a doc naming `$PIPE teleport` - "
                                 "it cannot catch the drift it exists to catch")


def init_stdout_is_machine_readable():
    """S25 - init is the first command of every run and the only place a caller learns
    the runId, the branch and the bus path. Its stdout has to parse."""
    with tempfile.TemporaryDirectory() as tmp:
        home = os.path.join(tmp, "aohome")
        for name, extra in (("legacy", []), ("workstream", ["--slug", "messaging-hub"])):
            cwd = os.path.join(tmp, name)
            os.makedirs(cwd)
            r = subprocess.run([sys.executable, PIPE, "init", "--feature", "Hub", *extra],
                               cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                               env={**os.environ, "AGENT_ORCHESTRATION_HOME": home})
            assert r.returncode == 0, r.stderr
            try:
                out = json.loads(r.stdout)
            except json.JSONDecodeError as e:
                raise AssertionError(
                    f"`init{' ' + ' '.join(extra) if extra else ''}` stdout is not JSON ({e}); "
                    f"tail is {r.stdout.strip().splitlines()[-1]!r}. A caller doing "
                    "json.loads(stdout) to read runId/branch now breaks.")
            assert out.get("runId"), out
            if extra:
                assert out.get("branch") == "feature/messaging-hub", out


def archive_never_moves_what_the_bus_does_not_own():
    """S26 - archive_bus moved the bus's PARENT. Under `--root <proj>/pipeline` that
    parent is the user's project directory, so closing a run carried a sibling
    src/app.py off with it. Every earlier scenario used a dedicated <tmp>/bus/pipeline,
    whose parent the bus really does own, so the destructive case never arose.

    The owning-parent half stays where it already is: workstream_checks asserts a bus
    under <tmp>/bus/pipeline archives the whole parent as <slug>.closed-<date>."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        proj = os.path.join(tmp, "proj")
        os.makedirs(os.path.join(proj, "src"))
        write(os.path.join(proj, "src", "app.py"), "print('keep me')\n")
        write(os.path.join(proj, "README.md"), "the user's project\n")
        root = os.path.join(proj, "pipeline")
        run(root, "init", "--feature", "Archive safety", "--slug", "archive-safety")
        repo = git_repo(os.path.join(tmp, "repos", "api"), "main")
        run(root, "worktree", "add", "--service", "api", "--repo", repo)
        wt = read_run(root)["repos"][0]["worktree"]
        write(os.path.join(wt, "a.txt"), "work\n")
        git(wt, "add", "-A"); git(wt, "commit", "-qm", "T1: work")

        out = run(root, "finish", "--apply")
        assert os.path.isfile(os.path.join(proj, "src", "app.py")), \
            "finish --apply moved the bus's PARENT: the sibling src/app.py went with " \
            f"the archive. Output was:\n{out}"
        assert os.path.isfile(os.path.join(proj, "README.md")), "sibling file taken too"
        assert os.path.isdir(proj), "the project directory itself was moved aside"
        assert not os.path.exists(root), "the bus was not archived at all"
        closed = [d for d in os.listdir(proj) if d.startswith("pipeline.closed-")]
        assert len(closed) == 1, f"expected one pipeline.closed-<date> in proj: {os.listdir(proj)}"
        assert sorted(os.listdir(proj)) == sorted(["README.md", "src", closed[0]]), \
            f"the project directory gained or lost entries: {os.listdir(proj)}"
        assert not [d for d in os.listdir(tmp) if ".closed-" in d], \
            f"something was archived a level above the bus: {os.listdir(tmp)}"
        assert os.path.isfile(os.path.join(proj, closed[0], "run.json")), \
            "the archive does not contain the bus it was supposed to move"


def qa_check_fails_when_a_review_is_missing():
    """S27 - a missing review.json read as `{}`: no findings, therefore no blocking
    findings, therefore green - while a missing results.json two lines below correctly
    failed. Every earlier qa-check assertion wrote a review first, so a bus the
    reviewer never reported on passed the gate."""
    with tempfile.TemporaryDirectory() as tmp:
        good = os.path.join(tmp, "review.json")
        write(good, json.dumps({"recommendation": "approve", "findings": []}))

        # results present, review absent -> must fail, naming the file
        a = os.path.join(tmp, "a", "pipeline")
        run(a, "init", "--feature", "no review")
        run(a, "task", "add", "--id", "T1", "--title", "x")
        run(a, "task", "update", "--id", "T1", "--status", "done")
        write(os.path.join(a, "test", "results.json"),
              json.dumps({"iteration": 1, "passed": 3, "failed": 0}))
        assert not os.path.exists(os.path.join(a, "review", "review.json"))
        out = run(a, "qa-check", expect=1)
        assert "review/review.json" in out, \
            f"the gate passed (or failed anonymously) with no review on the bus:\n{out}"

        # the mirror, which always worked: review present, results absent
        b = os.path.join(tmp, "b", "pipeline")
        run(b, "init", "--feature", "no results")
        run(b, "task", "add", "--id", "T1", "--title", "x")
        run(b, "task", "update", "--id", "T1", "--status", "done")
        run(b, "review", "--from", good)
        out = run(b, "qa-check", expect=1)
        assert "test/results.json" in out, out

        # and with both, the same bus is green - the gate is not simply always red
        run(a, "review", "--from", good)
        assert "green" in run(a, "qa-check")


# 7 of the 15 service names in the user's real registry. The m1 fix guarded --service
# with the SLUG predicate and rejected every one of them: `worktree add` could not
# build any multi-service workstream this project has ever run. The suite used only
# lowercase names ('api', 'web', 'billing', 'svc') and stayed green throughout.
REGISTRY_SERVICES = ["GT-Janus", "GTID-Vault", "MFA_Server", "SAML2_server_v251024",
                     "oauth_v3.8.0", "service_v3.8.5", "GTID_Radius"]


def real_service_names_survive_byte_for_byte():
    """S28 - a service name is a directory that ALREADY EXISTS, named by whoever made
    the repo. Capitals, underscores and dots are ordinary there, and wt-<slug>/<service>
    has to reproduce the exact bytes."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        repos_root = os.path.join(tmp, "repos")
        root = os.path.join(tmp, "bus", "pipeline")
        run(root, "init", "--feature", "Step up", "--slug", "stepup")
        container = os.path.join(repos_root, "wt-stepup")
        for name in REGISTRY_SERVICES:
            repo = git_repo(os.path.join(repos_root, name), "main")
            run(root, "worktree", "add", "--service", name, "--repo", repo)
            entry = read_run(root)["repos"][-1]
            assert entry["service"] == name, \
                f"repos[] rewrote the service name: {entry['service']!r} != {name!r}"
            assert entry["worktree"] == os.path.join(container, name), entry["worktree"]
            assert os.path.isdir(entry["worktree"]), f"no worktree at {entry['worktree']}"
            assert name in os.listdir(container), \
                f"{name!r} did not land on disk byte-for-byte: {os.listdir(container)}"
        assert [e["service"] for e in read_run(root)["repos"]] == REGISTRY_SERVICES


# Traversal is the whole threat a service name carries, and it reaches disk through
# two doors: worktree add (wt-<slug>/<service>) and svc_dir (review/qa-check artifacts).
BAD_SEGMENTS = ["../../x", "..", ".", "a/b", "a\\b", "C:\\tmp", "/etc", ""]


def paths_under(top):
    return sorted(os.path.relpath(os.path.join(d, n), top)
                  for d, dirs, files in os.walk(top) for n in dirs + files)


def a_service_name_cannot_escape_its_container():
    """S29 - `review --from x --service ../../x` wrote outside the bus: the m1 fix
    guarded worktree add only. svc_dir is now the single funnel, so both doors are
    tested, and nothing may appear outside the container either way."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        root = os.path.join(tmp, "bus", "pipeline")
        run(root, "init", "--feature", "Guard", "--slug", "guard")
        repo = git_repo(os.path.join(tmp, "repos", "api"), "main")
        good = os.path.join(tmp, "review.json")
        write(good, json.dumps({"recommendation": "approve", "findings": []}))
        before = paths_under(tmp)
        for bad in BAD_SEGMENTS:
            out = run(root, "worktree", "add", "--service", bad, "--repo", repo, expect=1)
            assert "--service" in out, f"worktree add accepted or misreported {bad!r}:\n{out}"
            out = run(root, "review", "--from", good, "--service", bad, expect=1)
            assert "--service" in out, f"review accepted or misreported {bad!r}:\n{out}"
        assert paths_under(tmp) == before, \
            "a refused --service still created something on disk: " \
            f"{sorted(set(paths_under(tmp)) - set(before))}"


def an_explicit_empty_service_is_not_the_flat_layout():
    """S30 - `if not service` made `--service ""` indistinguishable from omitting it,
    so a multi-service run's artifacts dropped into the flat slot the namespace exists
    to keep them out of. `is None` separates the two; omitting it must still work."""
    with tempfile.TemporaryDirectory() as tmp:
        root = os.path.join(tmp, "pipeline")
        run(root, "init", "--feature", "Empty service")
        good = os.path.join(tmp, "review.json")
        write(good, json.dumps({"recommendation": "approve", "findings": []}))
        flat = os.path.join(root, "review", "review.json")

        run(root, "review", "--from", good, "--service", "", expect=1)
        assert not os.path.exists(flat), \
            'an explicit --service "" collapsed into the flat single-service layout'

        run(root, "review", "--from", good)          # omitted: unchanged, still flat
        assert os.path.isfile(flat), "omitting --service must still write review/review.json"
        assert os.path.isfile(os.path.join(root, "review", "review.md"))


def a_mid_loop_merge_failure_names_the_half_shipped_repos():
    """M1 - preflight makes a failure in the merge loop unlikely, not impossible. When
    repo 2 fails after repo 1 merged, the operator needs the state named and the undo
    spelled out; git has no multi-repo rollback. Provoked with a pre-merge-commit hook,
    which is the cheapest real mid-loop failure - no machinery, no monkeypatching."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        root = workstream(tmp, "halfship", [("api", "main"), ("web", "main")])
        commit_work(root)
        repos = read_run(root)["repos"]
        api, web = repos[0]["repo"], repos[1]["repo"]
        hook = os.path.join(web, ".git", "hooks", "pre-merge-commit")
        write(hook, "#!/bin/sh\nexit 1\n")
        os.chmod(hook, 0o755)
        before = git(api, "rev-parse", "HEAD").strip()

        out = run(root, "finish", "--apply", expect=1)
        assert "HALF-SHIPPED: 1 of 2" in out, f"the half-shipped state is not named:\n{out}"
        assert api in out, f"the merged repo is not named:\n{out}"
        assert f"git -C {api} reset --hard ORIG_HEAD" in out, \
            f"the undo for the already-merged repo is not spelled out:\n{out}"
        assert git(api, "rev-parse", "HEAD").strip() != before, \
            "the report claims a half-shipped merge that did not happen"
        assert os.path.isfile(os.path.join(root, "run.json")), \
            "a failed --apply archived the bus anyway - the operator needs it to retry"


def ls_reports_branch_drift_and_orphan_containers():
    """S32 - AC12. The two drift states nobody notices until a merge silently leaves a
    repo behind: two branch names inside one workstream (2 of 11 real containers), and a
    wt-<slug>/ container whose bus is gone. Each half is mutated: equal branches must
    stop the drift assertion firing, so it cannot be passing on a constant."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        home = os.path.join(tmp, "aohome")
        env = {"AGENT_ORCHESTRATION_HOME": home}
        root = os.path.join(home, "pipelines", "twowave", "pipeline")
        run(root, "init", "--feature", "Two branches", "--slug", "twowave", env=env)
        repos = os.path.join(tmp, "repos")
        for svc, base in (("api", "develop"), ("web", "master")):
            run(root, "worktree", "add", "--service", svc,
                "--repo", git_repo(os.path.join(repos, svc), base), env=env)

        rj = os.path.join(root, "run.json")
        data = read_json(rj)
        one = data["repos"][0]["branch"]
        data["repos"][1]["branch"] = "feature/twowave-web"
        write(rj, json.dumps(data, indent=2))
        out = run(root, "ls", env=env)
        assert "twowave" in out and "branch-drift" in out, \
            f"ls does not name a workstream whose repos sit on two branch names:\n{out}"

        data["repos"][1]["branch"] = one                   # the mutation half
        write(rj, json.dumps(data, indent=2))
        out = run(root, "ls", env=env)
        assert "branch-drift" not in out, f"ls reports drift on a workstream that has none:\n{out}"

        os.makedirs(os.path.join(repos, "wt-ghost", "api"))
        out = run(root, "ls", env=env)
        assert "wt-ghost" in out and "orphan" in out, \
            f"a wt-<slug>/ container with no bus is invisible to ls:\n{out}"


def prune_lists_before_it_removes():
    """S33 - AC12. prune follows finish's plan/apply shape: an archived workstream's
    container is NAMED by a bare prune and still on disk afterwards, and only --apply
    removes it. Mutate the default branch to delete and the first half fails."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        home = os.path.join(tmp, "aohome")
        env = {"AGENT_ORCHESTRATION_HOME": home}
        root = os.path.join(home, "pipelines", "closing", "pipeline")
        run(root, "init", "--feature", "Closing", "--slug", "closing", env=env)
        repo = git_repo(os.path.join(tmp, "repos", "api"), "main")
        run(root, "worktree", "add", "--service", "api", "--repo", repo, env=env)
        wt = read_run(root)["repos"][0]["worktree"]
        container = os.path.dirname(wt)
        write(os.path.join(wt, "a.txt"), "work\n")
        git(wt, "add", "-A"); git(wt, "commit", "-qm", "T1: work")
        run(root, "finish", "--apply", env=env)          # archives the bus, keeps the worktree
        assert os.path.isdir(container), "finish without --teardown keeps the container"

        # prune's root is the fixed pipelines root, not --root; any path will do here
        nowhere = os.path.join(tmp, "not-a-bus", "pipeline")
        out = run(nowhere, "prune", env=env)
        assert container in out, f"prune does not name the archived container:\n{out}"
        assert os.path.isdir(container), \
            "a bare prune removed a container - it must plan, like finish does"

        out = run(nowhere, "prune", "--apply", env=env)
        assert not os.path.exists(container), f"--apply left the container behind:\n{out}"
        assert container not in git(repo, "worktree", "list"), \
            "the worktree registration outlived the directory - git worktree prune never ran"


def prune_gives_back_a_done_workstreams_worktrees_once_its_work_has_landed():
    """S59. A run that reaches `done` and is never `finish`ed kept its worktrees forever -
    19 of 24 real buses were done and none archived. prune now covers them, and /ship runs
    it with --apply, so it removes only what cannot lose work: a clean tree whose branch is
    merged or pushed. An unlanded branch, a dirty tree and a live run all stay, and the
    branch itself always survives. Each keep is a mutation of the one removal."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        home = os.path.join(tmp, "aohome")
        env = {"AGENT_ORCHESTRATION_HOME": home}
        repo = git_repo(os.path.join(tmp, "repos", "api"), "main")
        remote = os.path.join(tmp, "remote.git")
        git(tmp, "init", "-q", "--bare", remote)
        git(repo, "remote", "add", "origin", remote)
        wts = {}
        for slug in ("pushed", "unlanded", "dirty", "live"):
            root = os.path.join(home, "pipelines", slug, "pipeline")
            run(root, "init", "--feature", slug, "--slug", slug, env=env)
            run(root, "worktree", "add", "--service", "api", "--repo", repo, env=env)
            wt = wts[slug] = read_run(root)["repos"][0]["worktree"]
            write(os.path.join(wt, slug + ".txt"), "work\n")
            git(wt, "add", "-A"); git(wt, "commit", "-qm", slug)
            if slug != "live":
                run(root, "set-status", "done", env=env)
        git(wts["pushed"], "push", "-q", "origin", "feature/pushed")
        git(repo, "merge", "-q", "--no-ff", "-m", "merge dirty", "feature/dirty")
        git(repo, "merge", "-q", "--no-ff", "-m", "merge live", "feature/live")
        write(os.path.join(wts["dirty"], "scratch.txt"), "not committed\n")

        nowhere = os.path.join(tmp, "not-a-bus", "pipeline")
        out = run(nowhere, "prune", env=env)
        assert "would remove worktree " + wts["pushed"] in out, \
            f"a bare prune does not name the pushed, clean, done worktree:\n{out}"
        assert all(os.path.isdir(w) for w in wts.values()), \
            "a bare prune removed a worktree - it must plan, like finish does"

        out = run(nowhere, "prune", "--apply", env=env)
        assert not os.path.exists(wts["pushed"]), f"--apply left the landed worktree:\n{out}"
        assert not os.path.exists(os.path.dirname(wts["pushed"])), \
            f"its emptied container was left behind:\n{out}"
        assert git(repo, "rev-parse", "--verify", "feature/pushed").strip(), \
            "prune deleted the branch - it may only remove the checkout"
        for slug, why in (("unlanded", "not pushed"), ("dirty", "uncommitted changes")):
            assert os.path.isdir(wts[slug]), f"prune removed the {slug} worktree:\n{out}"
            assert why in out, f"prune kept {slug} without saying why ({why!r}):\n{out}"
        assert os.path.isdir(wts["live"]) and wts["live"] not in out, \
            f"prune looked at a workstream that is still running:\n{out}"


def the_gate_round_trips_beside_the_bus():
    """S34 - AC5, the terminal half. `gate` then `wait` releases, prints the decision,
    and the file lands BESIDE the bus (section 3), not inside it - server.js mirrors
    that one path and a gate written into the bus would be archived away with it."""
    with tempfile.TemporaryDirectory() as tmp:
        root = os.path.join(tmp, "workstream", "pipeline")
        run(root, "init", "--feature", "Gate me", "--slug", "gate-me")
        assert "finalize" in run(root, "gate", "--decision", "finalize")
        assert os.path.isfile(os.path.join(tmp, "workstream", "gate.json")), \
            f"gate.json is not beside the bus: {os.listdir(os.path.join(tmp, 'workstream'))}"
        assert not os.path.exists(os.path.join(root, "gate.json"))
        assert run(root, "wait", "--for", "gate", "--timeout", "5").strip() == "finalize"
        run(root, "gate", "--decision", "nope", expect=2)      # argparse refuses it


def a_previous_runs_gate_does_not_release_this_one():
    """S35 - the scenario most worth watching fail. gate.json is durable on purpose
    (re-arming a watcher must pick up an approval that already landed), but a workstream
    outlives its runs (section 3.3), so wave 1's gate sitting in the workstream directory
    would auto-finalize wave 2 the instant its watcher armed - approving a plan nobody
    read. `wait` ignores a gate stamped with another runId and keeps waiting."""
    with tempfile.TemporaryDirectory() as tmp:
        ws = os.path.join(tmp, "workstream")
        root = os.path.join(ws, "pipeline")
        run(root, "init", "--feature", "Wave 1", "--slug", "waves")
        run(root, "gate", "--decision", "finalize")
        wave1 = read_json(os.path.join(ws, "gate.json"))["runId"]

        run(root, "init", "--feature", "Wave 2", "--slug", "waves")   # same workstream
        assert read_run(root)["runId"] != wave1, "wave 2 did not get its own runId"
        out = run(root, "wait", "--for", "gate", "--timeout", "1", expect=1)
        assert "wait:" in out, out
        assert read_json(os.path.join(ws, "gate.json"))["runId"] == wave1, \
            "wait must not consume or rewrite the gate it ignored"

        run(root, "gate", "--decision", "in-place")                   # this run's answer
        assert run(root, "wait", "--for", "gate", "--timeout", "5").strip() == "in-place"


REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_JS = os.path.join(REPO, "ui", "server.js")


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def http_json(port, path, payload=None, method=None):
    """(status, body) over loopback. An HTTP error code is an answer, not an exception."""
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data,
                                 method=method or ("POST" if data else "GET"),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


class Server:
    """`node ui/server.js` against a throwaway AGENT_ORCHESTRATION_HOME."""
    def __init__(self, home):
        self.port = free_port()
        self.p = subprocess.Popen(
            ["node", SERVER_JS, "--port", str(self.port)],
            env={**os.environ, "AGENT_ORCHESTRATION_HOME": home},
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    def __enter__(self):
        for _ in range(80):                       # ~20 s: node is slow to boot on Windows
            try:
                http_json(self.port, "/api/hall")
                return self
            except Exception:
                if self.p.poll() is not None:
                    raise AssertionError("server.js exited: " + self.p.communicate()[0])
                time.sleep(0.25)
        raise AssertionError("server.js never answered on 127.0.0.1")

    def __exit__(self, *a):
        self.p.terminate()
        try: self.p.wait(timeout=5)
        except subprocess.TimeoutExpired: self.p.kill()


def the_gate_endpoint_is_the_security_boundary():
    """S36 - AC5/AC4, spec section 14. POST /api/gate is the first path where a browser
    can move a run forward, so every input is checked at the door: three fixed decisions,
    a slug resolved by identity against the scan list (never joined to a path), a capped
    body, and a gate.json that `pipe.py wait` then accepts. Skips - never fails - when
    node is absent, because a suite that silently passes without it proves nothing."""
    if not shutil.which("node"):
        print("SKIP S36 - no node on PATH; the /api/gate endpoint was not exercised")
        return
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        home = os.path.join(tmp, "aohome")
        env = {"AGENT_ORCHESTRATION_HOME": home}
        root = os.path.join(home, "pipelines", "browser-gate", "pipeline")
        run(root, "init", "--feature", "Browser gate", "--slug", "browser-gate", env=env)
        before = paths_under(tmp)
        with Server(home) as s:
            code, body = http_json(s.port, "/api/gate",
                                   {"slug": "browser-gate", "decision": "ship-it"})
            assert code == 400 and "decision" in body, (code, body)

            code, body = http_json(s.port, "/api/gate",
                                   {"slug": "no-such-run", "decision": "finalize"})
            assert code == 404 and "slug" in body, (code, body)

            code, body = http_json(s.port, "/api/gate",
                                   {"slug": "../../etc", "decision": "finalize"})
            assert code == 404, f"a traversal-shaped slug must resolve to nothing: {code} {body}"

            code, body = http_json(s.port, "/api/gate",
                                   {"slug": "browser-gate", "decision": "x" * 5000})
            assert code in (400, 413), f"an oversized body must be refused: {code}"

            code, body = http_json(s.port, "/api/gate",
                                   {"slug": "browser-gate", "decision": "finalize"})
            assert code == 200, (code, body)

        gate = os.path.join(home, "pipelines", "browser-gate", "gate.json")
        assert os.path.isfile(gate), \
            f"the endpoint wrote no gate beside the bus: {paths_under(tmp)}"
        assert json.loads(open(gate, encoding="utf-8").read())["by"] == "browser"
        assert run(root, "wait", "--for", "gate", "--timeout", "5", env=env).strip() \
            == "finalize", "pipe.py wait does not accept the gate the browser wrote"

        new = set(paths_under(tmp)) - set(before)
        assert new == {os.path.relpath(gate, tmp)}, \
            f"the endpoint touched something other than one gate.json: {sorted(new)}"


def both_gate_writers_agree_on_the_format():
    """S37 - two writers of one file (pipe.py cmd_gate and server.js), which discipline
    does not keep in agreement. Close it mechanically: the keys server.js writes must be
    exactly the keys pipe.py writes and cmd_wait reads, and the three accepted decisions
    must be the same three. Rename a key in either file and this fails."""
    src = open(SERVER_JS, encoding="utf-8").read()
    m = re.search(r"function gateRecord\([^)]*\)\s*\{.*?return\s*\{(.*?)\};", src, re.S)
    assert m, "ui/server.js has no gateRecord() to compare against - the guard is blind"
    js_keys = set(re.findall(r"(\w+):", m.group(1)))

    with tempfile.TemporaryDirectory() as tmp:
        root = os.path.join(tmp, "workstream", "pipeline")
        run(root, "init", "--feature", "Format", "--slug", "format")
        run(root, "gate", "--decision", "reject")
        py_keys = set(json.loads(
            open(os.path.join(tmp, "workstream", "gate.json"), encoding="utf-8").read()))
    assert js_keys == py_keys, \
        f"the two gate writers disagree: server.js {sorted(js_keys)} vs pipe.py {sorted(py_keys)}"
    assert "runId" in py_keys, "wait's previous-run guard reads runId - it must be written"

    js_decisions = re.search(r"GATE_DECISIONS\s*=\s*\[(.*?)\]", src, re.S)
    assert js_decisions, "ui/server.js does not declare GATE_DECISIONS"
    assert re.findall(r'"([^"]+)"', js_decisions.group(1)) == import_pipe().GATE_DECISIONS, \
        "server.js accepts a different set of decisions from pipe.py"


def the_listen_call_is_explicit_about_loopback():
    """S38 - section 14. Asserting the negative (that the machine's external address is
    not serving) would need this machine's external address; the literal is the cheap
    guard that survives a refactor of the surrounding lines."""
    src = open(SERVER_JS, encoding="utf-8").read()
    assert 'listen(PORT, "127.0.0.1"' in src, \
        "ui/server.js binds every interface, with a git-adjacent POST endpoint behind it"


def a_hide_lasts_for_the_run_it_was_made_in():
    """S60. POST /api/hide is the gate's door with a boolean behind it: a slug resolved by
    identity, a refused non-boolean, and one hidden.json beside the bus. The record names
    its runId, so a new wave of a hidden workstream comes back by itself instead of
    running where nobody is looking - mutate the runId and the hide must lapse."""
    if not shutil.which("node"):
        print("SKIP S60 - no node on PATH; the /api/hide endpoint was not exercised")
        return
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        home = os.path.join(tmp, "aohome")
        env = {"AGENT_ORCHESTRATION_HOME": home}
        root = os.path.join(home, "pipelines", "tucked", "pipeline")
        run(root, "init", "--feature", "Tucked away", "--slug", "tucked", env=env)
        record = os.path.join(home, "pipelines", "tucked", "hidden.json")

        def hidden(port):
            code, body = http_json(port, "/api/hall")
            assert code == 200, (code, body[:200])
            return [p for p in json.loads(body)["pipelines"] if p["slug"] == "tucked"][0]["hidden"]

        with Server(home) as s:
            code, body = http_json(s.port, "/api/hide", {"slug": "tucked", "hidden": "yes"})
            assert code == 400 and "hidden" in body, (code, body)
            code, body = http_json(s.port, "/api/hide", {"slug": "../../etc", "hidden": True})
            assert code == 404, f"a traversal-shaped slug must resolve to nothing: {code} {body}"
            assert hidden(s.port) is False

            assert http_json(s.port, "/api/hide", {"slug": "tucked", "hidden": True})[0] == 200
            assert os.path.isfile(record), "the hide was not written beside the bus"
            assert not os.path.exists(os.path.join(root, "hidden.json"))
            assert hidden(s.port) is True, "/api/hall does not report the hide"

            rj = os.path.join(root, "run.json")
            data = read_json(rj)
            data["runId"] = "run-a-later-wave"
            write(rj, json.dumps(data, indent=2))
            assert hidden(s.port) is False, "a hide outlived its run - a new wave would run unseen"

            assert http_json(s.port, "/api/hide", {"slug": "tucked", "hidden": True})[0] == 200
            assert http_json(s.port, "/api/hide", {"slug": "tucked", "hidden": False})[0] == 200
            assert not os.path.exists(record) and hidden(s.port) is False, "unhide left it hidden"


HALL_HTML = os.path.join(REPO, "ui", "hall.html")

# Section 10.1's two tables, by name. The palette was arrived at by iteration and is
# binding, so the guard is that every token is declared - not that it looks right.
SECTION_10_1_TOKENS = [
    "ink", "panel", "sunk", "raise", "line", "line-2", "text", "bright", "muted", "faint",
    "planner", "coder", "tester", "reviewer", "orch", "ok", "warn", "bad", "felt",
    "floor", "floor-2", "grout", "wall", "wall-edge", "wall-shadow",
    "wood", "wood-2", "deskglass", "chairc", "chairc-2", "skin", "legs", "shoe",
    "eye", "pupil", "screen", "screen-b", "pot", "leaf",
]


def the_board_matches_the_hall_and_needs_no_network():
    """S49 - section 10.6. board.html duplicates the section 10.1 tokens rather than
    sharing a stylesheet route, which is only defensible while something stops the two
    copies drifting. Every role and status colour must be byte-identical to the hall's,
    and the board must render with no network for the same reason the hall must."""
    board = os.path.join(REPO, "ui", "board.html")
    assert os.path.isfile(board), "ui/board.html is missing - /r/<slug> has no board"
    b = open(board, encoding="utf-8").read()
    h = open(HALL_HTML, encoding="utf-8").read()

    assert "fonts.googleapis" not in b and not re.search(r"<link[^>]+href=[\"']https?:", b), \
        "board.html reaches the network for type"

    for tok in ("planner", "coder", "tester", "reviewer", "orch", "ok", "warn", "bad"):
        hv = re.findall(rf"--{tok}\s*:\s*(#[0-9A-Fa-f]{{6}})", h)
        bv = re.findall(rf"--{tok}\s*:\s*(#[0-9A-Fa-f]{{6}})", b)
        assert bv, f"board.html declares no --{tok}"
        assert set(bv) <= set(hv), \
            f"--{tok} has drifted from the hall: board {sorted(set(bv))} vs hall {sorted(set(hv))}"

    # Section 10.6's own claims: six columns in order, and the matrix counts cumulatively.
    for col in ("To do", "Coding", "Ready for QA", "QA", "Review", "Done"):
        assert col in b, f"the task flow is missing the {col!r} column"
    assert "reached review" not in b, "the lane head still counts tasks instead of the time left"
    # AC11: the clock-derived figures repaint every 30 s between bus writes.
    assert re.search(r"setInterval\(\(\)=>\{\s*timeband\(\);.*?\},30000\)", b, re.S),         "board.html does not repaint the time band every 30 s"


def a_coded_task_is_not_done_until_its_service_is():
    """S58 - only the coder ever moves a task, so `done` means "written once". The board
    put every such card in Done, which read a run four fix loops deep as finished. The
    column has to follow the service's stage. Runs board.html's own column() in node."""
    if not shutil.which("node"):
        print("SKIP S58 - no node on PATH; board column() was not exercised")
        return
    src = open(os.path.join(REPO, "ui", "board.html"), encoding="utf-8").read()
    block = re.search(r"(const STATUS_COL=.*?)\nlet S=", src, re.S)
    assert block, "board.html no longer has STATUS_COL ... column() ahead of `let S=`"
    svc = lambda phase, agent, count, status="running": \
        {"phase": phase, "activeAgent": agent, "loop": {"count": count, "max": 5}, "status": status}
    multi = lambda s, phase="implement", status="running": \
        {"phase": phase, "status": status, "services": {"vault": s}}
    done = {"id": "T1", "status": "done", "owner": "coder", "service": "vault"}
    cases = [  # (run, task, column) - the multi-service rows are federated-mcp-login's
        (multi(svc("implement", "coder", 4)), done, "coding"),     # a fix pass
        (multi(svc("test", "tester", 4)), done, "qa"),
        (multi(svc("implement", "coder", 0)), done, "readyqa"),    # first pass
        (multi(svc("test", "tester", 2, "done")), done, "review"),  # green, not reviewed
        (multi(svc("test", "tester", 2, "done"), "review"), done, "review"),
        (multi(svc("test", "tester", 2, "done"), "qa"), done, "done"),
        (multi(svc("test", "tester", 2, "done"), "review", "done"), done, "done"),
        ({"phase": "test", "activeAgent": "coder", "loop": {"count": 1}}, done, "coding"),
        ({"phase": "test", "activeAgent": "tester", "loop": {"count": 1}}, done, "qa"),
        ({"phase": "implement", "activeAgent": "coder"}, done, "readyqa"),
        (multi(svc("implement", "coder", 0)), {"status": "in_progress", "owner": "coder"}, "coding"),
        (multi(svc("implement", "coder", 0)), {"status": "todo"}, "todo"),
    ]
    js = ("var S;\n" + block.group(1) + "\nconst bad=[];\n"
          "for(const [run,t,want] of " + json.dumps(cases) + "){S={run};"
          "const got=column(t); if(got!==want) bad.push(JSON.stringify({run,t,want,got}));}\n"
          "if(bad.length){console.log(bad.join('\\n'));process.exit(1);}")
    r = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, f"board column() put a card in the wrong column:\n{r.stdout}{r.stderr}"


def the_hall_carries_its_palette_and_needs_no_network():
    """S39 - AC4, section 10.1. Two themes resolved three ways, and a page that renders
    with no network: ui/server.js is dependency-free and serves localhost, so a webfont
    <link> to a CDN would make the product's type depend on a request it cannot make.
    Declaring a token in one theme and forgetting the other is the failure this catches."""
    src = open(HALL_HTML, encoding="utf-8").read()

    assert "fonts.googleapis" not in src and "fonts.gstatic" not in src, \
        "hall.html pulls a webfont from a CDN - it must render with no network"
    assert not re.search(r"<link[^>]+href=[\"']https?:", src), \
        "hall.html loads a remote stylesheet"
    assert "ui-monospace" in src and "system-ui" in src, \
        "Fira is declared without the real system fallbacks it degrades to"

    # The three-way resolution: bare :root is light, system dark is guarded so an
    # explicit light toggle wins, and an explicit dark toggle wins in both directions.
    for selector in ['@media (prefers-color-scheme:dark)',
                     ':root:not([data-theme="light"])',
                     ':root[data-theme="dark"]']:
        assert selector.replace(" ", "") in src.replace(" ", ""), \
            f"hall.html never resolves the theme through {selector}"

    missing = [t for t in SECTION_10_1_TOKENS if len(re.findall(rf"--{re.escape(t)}\s*:", src)) < 3]
    assert not missing, \
        f"section 10.1 tokens not declared in all three theme blocks: {missing}"
    # Spot-check one value per table per theme: a token declared with the wrong colour
    # passes the count above.
    for value in ("#E7EAF0", "#121822", "#DFE4EA", "#161C26"):
        assert value in src, f"section 10.1 value {value} is missing from hall.html"


def the_root_route_serves_the_hall():
    """S50 - AC4. `/` is the hall and `/r/<slug>` stays the existing board. Skips - never
    fails - without node, because a suite that passes silently proves nothing."""
    if not shutil.which("node"):
        print("SKIP S50 - no node on PATH; the / route was not exercised")
        return
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        home = os.path.join(tmp, "aohome")
        root = os.path.join(home, "pipelines", "hall-route", "pipeline")
        run(root, "init", "--feature", "Hall route", "--slug", "hall-route",
            env={"AGENT_ORCHESTRATION_HOME": home})
        with Server(home) as s:
            code, body = http_json(s.port, "/")
            assert code == 200 and 'id="hall"' in body, \
                f"/ does not serve ui/hall.html: {code} {body[:200]}"
            code, body = http_json(s.port, "/r/hall-route")
            # The finalize gate scoped this to the OLD board; the user reversed that after
            # seeing it, so /r/<slug> is now section 10.6's three-pane board.
            assert code == 200 and 'id="board"' in body, \
                f"/r/<slug> must serve ui/board.html: {code} {body[:200]}"


CAST = ["planner", "coder", "tester", "reviewer", "orch"]


def every_character_has_both_hair_layers():
    """S51 - AC4, section 10.3, redrawn for ADR-0006's hall. The cast is one drawn character
    now, not a sheet of pixel symbols, but the rule it was guarding is the same: seen from
    behind there is no face to leave room for, so the hair must fill the whole skull -
    without that the near pair render as bare scalps with a fringe balanced on them."""
    src = open(HALL_HTML, encoding="utf-8").read()

    body = re.search(r"function sprite\(.*?\n\}", src, re.S)
    assert body, "hall.html has no sprite() - nothing draws the cast"
    assert "rear" in body.group(0) and "<circle" in body.group(0), \
        "sprite() draws no full-skull hair for an agent seen from behind"
    assert 'sleep' in body.group(0), \
        "sprite() must never turn a sleeping agent around - there would be no shut eyes to see"

    # Hair is what tells the five apart, so each role has its own and it ignores the theme.
    for role in CAST:
        assert re.search(rf"\.who \.h-{role}\{{fill:#[0-9A-F]{{6}}\}}", src), \
            f"the cast has no hair colour for {role} - that seat renders as a blank head"
    assert "var(--pupil)" in src, "the eyes do not use the dedicated near-black --pupil token"

    # Section 10.8-1: a fifth seat on the bottom edge, only when the run has an operator.
    assert "function hasOperator(" in src, \
        "nothing decides whether the operator's fifth seat exists - it must not always render"


# Section 10.4's eight entries, as they appear in CSS. Baton travel is a transition
# rather than a loop, so it has no @keyframes and is checked by its duration below.
MOTION_KEYFRAMES = {"typing", "waiting", "sleeping", "walk-in", "table-in", "row-in",
                    "going-quiet"}
# Section 10.5's scrolling screen is the office's own "something is happening here". It
# is specified separately from the inventory, and it is the only addition allowed.
# The drawn cast (ADR-0006's hall) adds its own three - hands on the keys, a blink, a
# sleeper's z. They ride on the typing/waiting/asleep entries rather than adding states.
# Asking for help adds a raised hand that waves (a gate) and a shake (blocked).
MOTION_ALLOWED = MOTION_KEYFRAMES | {"screen-scroll", "tap", "blink", "zz", "wave", "shake"}


def the_motion_inventory_stays_at_eight():
    """S52 - AC4, section 10.4. Eight entries and six rules: if this list grows to twenty,
    that is the bug. The rules are mechanical, so check them mechanically - only transform
    and opacity ever animate (no layout, no paint), every loop is stepped, the stale team
    freezes, and prefers-reduced-motion stops all of it."""
    src = open(HALL_HTML, encoding="utf-8").read()

    css = re.sub(r"/\*.*?\*/", "", src, flags=re.S)   # the rules are quoted in comments
    names = set(re.findall(r"@keyframes\s+([\w-]+)", src))
    assert not MOTION_KEYFRAMES - names, \
        f"section 10.4 entries with no animation: {sorted(MOTION_KEYFRAMES - names)}"
    assert not names - MOTION_ALLOWED, \
        f"motion beyond the inventory: {sorted(names - MOTION_ALLOWED)} - that is the bug"

    # Rule 5: transform and opacity only, so a full hall stays smooth while the page works.
    for block in re.findall(r"@keyframes\s+[\w-]+\s*\{(.*)", src):
        for prop in re.findall(r"([a-z-]+)\s*:", block):
            assert prop in ("transform", "opacity"), \
                f"@keyframes animates {prop} - that is layout or paint, not transform/opacity"
    for value in re.findall(r"transition:([^;}]*)", css):
        head = value.strip().split()[0].replace("!important", "")
        assert head in ("transform", "opacity", "none"), \
            f"transition on {head} - rule 5 forbids it"
    assert "scale(0)" not in css, "rule 5 forbids scale(0)"
    assert not re.search(r"ease-in(?!-out)", css), "rule 5 forbids ease-in"

    # Rule 1: stepped, never eased. The snap is what makes a sprite look drawn.
    assert "steps(1)" in src and "steps(4)" in src, "the sprite loops are not stepped"
    for duration in ("340ms", "3.4s", "3.6s", "440ms", "260ms", "240ms", "2.6s"):
        assert duration in src, f"section 10.4 has an entry at {duration}; hall.html has none"

    # Rule 4: stillness is the alarm - a stale team freezes mid-keystroke and dims.
    assert re.search(r"animation-play-state:\s*paused", src), \
        "nothing freezes when a run goes quiet - in a hall where working things move, that is the signal"

    # Rule 6: every loop stops and the resting pose stays.
    rm = re.search(r"@media \(prefers-reduced-motion:\s*reduce\)\s*\{(.*?)\n  \}", src, re.S)
    assert rm and "animation:none" in rm.group(1) and "transition:none" in rm.group(1), \
        "prefers-reduced-motion does not stop every loop"


def js_literal(src, name):
    """The JSON-shaped literal assigned to `const <name> = ...;` in hall.html. The office
    geometry is data, so the guard reads the data rather than the drawing code."""
    m = re.search(rf"const {name}\s*=\s*(\[.*?\]|\{{.*?\}})\s*;", src, re.S)
    assert m, f"hall.html declares no {name} - the office geometry cannot be checked"
    return json.loads(re.sub(r"//[^\n]*", "", m.group(1)))


# Section 10.5: desk islands occupy these bands, so the walkable space is the two
# vertical aisles and the horizontal ones between and around them. Rows sit 206 apart,
# not the original 152: a rug overhangs its island by 8 above, and each island's state tag
# (top:-31px) must clear the nameplate and bar of the row above (bottom at +170).
ISLAND_X = [(18, 174), (212, 368), (406, 562)]
ISLAND_Y = [(16, 134), (222, 340)]


def the_corridor_graph_never_cuts_a_corner():
    """S43 - AC4, section 10.5. Walkers move one axis at a time: every edge in NODES /
    EDGES is purely horizontal or vertical, and its constant coordinate sits in an aisle.
    That is the whole reason the graph exists - a diagonal edge walks someone straight
    through a desk. Also pins the facing-pair offsets, which were chosen so that no agent
    is ever in front of a screen."""
    src = open(HALL_HTML, encoding="utf-8").read()
    nodes, edges = js_literal(src, "NODES"), js_literal(src, "EDGES")

    def in_aisle(v, bands):
        return all(not (lo <= v <= hi) for lo, hi in bands)

    for a, b in edges:
        assert a in nodes and b in nodes, f"edge {a}-{b} names a node that does not exist"
        (ax, ay), (bx, by) = nodes[a], nodes[b]
        assert (ax == bx) != (ay == by), \
            f"edge {a}-{b} is diagonal ({ax},{ay})->({bx},{by}) - it cuts through a desk"
        if ax == bx:
            assert in_aisle(ax, ISLAND_X), f"vertical edge {a}-{b} runs at x={ax}, inside an island"
        else:
            assert in_aisle(ay, ISLAND_Y), f"horizontal edge {a}-{b} runs at y={ay}, inside an island"
    for name, (x, y) in nodes.items():
        assert in_aisle(x, ISLAND_X) or in_aisle(y, ISLAND_Y), \
            f"node {name} at ({x},{y}) stands on a desk island"

    pod = {p["role"]: p for p in js_literal(src, "POD")}
    expect = {"planner": (26, 4, 25, 42), "coder": (96, 4, 95, 42),
              "tester": (26, 120, 25, 92), "reviewer": (96, 120, 95, 92)}
    for role, (x, y, dx, dy) in expect.items():
        got = pod.get(role)
        assert got and (got["x"], got["y"], got["dx"], got["dy"]) == (x, y, dx, dy), \
            f"{role}'s facing-pair offset drifted from section 10.5: {got}"
    assert pod["tester"]["back"] and pod["reviewer"]["back"], \
        "the bottom pair must be back: true - bodies sit on the outer edges"
    assert not pod["planner"]["back"] and not pod["coder"]["back"]

    # Section 10.8-2: the floor grows and off-screen pods stop animating. Capping it
    # would hide exactly the stalled pipelines the floor exists to surface.
    assert "IntersectionObserver" in src, \
        "nothing pauses off-screen pods; at twelve teams that is ~24 sprite loops"
    assert "const MEET" not in src, "the gate huddle is gone: agents stay seated, hands up"
    # AC10: fits on open and on resize, drags, zooms, each island carries its state tag,
    # and a completed team's pod is empty (no sprite in the pod markup).
    assert re.search(r"renderOffice\(\);\s*fitView\(\)", src) and         re.search(r'addEventListener\("resize",\(\)=>\{[^}]*fitView\(\)', src),         "the floor does not fit on open and on resize"
    assert "pointermove" in src and "e.ctrlKey" in src, "the floor cannot be dragged or zoomed"
    pod_fn = src[src.index("function podHTML"):src.index("function orchHTML")]
    assert "podTag(p,st)" in pod_fn, "each island must show its state tag"
    assert re.search(r"p\.completed\?\"\":POD\.map", pod_fn), "a completed pod still seats people"
    assert "566" in src and "466" in src, "the building is not the fixed 566x466 of 10.5"
    assert "2.5" in src and "0.5" in src, "the zoom range is not 0.5-2.5"


def the_hall_boots_from_the_bus_not_the_fixture():
    """S50 - AC4/AC5, the wiring. The hall existed for three agent attempts as a fully
    built, fully styled page rendering a hard-coded FIXTURE: it looked finished while
    showing four pipelines that were never real, which is the worst thing a dashboard can
    do. Assert the boot path reaches the bus, that the fixture is reachable only behind an
    explicit opt-in, and that a served / actually carries the wiring. Skips - never fails
    - without node, because a suite that quietly passes without it proves nothing."""
    src = open(HALL_HTML, encoding="utf-8").read()

    for needle, why in [("/api/hall", "the hall never fetches the scan"),
                        ("EventSource", "the hall never subscribes to /events"),
                        ("/api/gate", "the gate buttons write nowhere")]:
        assert needle in src, f"{why} - {needle} absent from hall.html"

    # The fixture must not be the boot. Every render(FIXTURE) has to sit inside the demo
    # opt-in; an unguarded one is precisely the defect this scenario exists to catch.
    calls = [m.start() for m in re.finditer(r"render\(FIXTURE\)", src)]
    assert calls, "the fixture is gone - ?demo=1 is how this page gets reviewed offline"
    guard = src.find('has("demo")')
    assert guard != -1, "no ?demo= opt-in guards the fixture"
    for at in calls:
        assert guard < at < guard + 400, \
            "render(FIXTURE) sits outside the ?demo= branch - the hall can boot on fake data"

    if not shutil.which("node"):
        print("SKIP S50 - no node on PATH; / was not served")
        return
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        home = os.path.join(tmp, "aohome")
        env = {"AGENT_ORCHESTRATION_HOME": home}
        root = os.path.join(home, "pipelines", "hall-boot", "pipeline")
        run(root, "init", "--feature", "Hall boot", "--slug", "hall-boot", env=env)
        with Server(home) as s:
            code, body = http_json(s.port, "/")
            assert code == 200, f"/ returned {code}"
            assert 'id="conn-txt"' in body, "/ did not serve hall.html in scan mode"
            for needle in ("/api/hall", "EventSource", "/api/gate"):
                assert needle in body, f"the served hall is missing {needle}"
            code, body = http_json(s.port, "/api/hall")
            assert code == 200 and "hall-boot" in body, (code, body[:200])


def slug_derivation_strips_decoration_at_either_end():
    """S51 - section 9. Decoration leads as well as trails, and stacks. A document
    carries a kind prefix and a date because documents need them; a branch name needs
    neither. GoTrust's real spec is SPEC-2026-09-21-entra-hold-and-deny.md, and leaving
    the prefix on produced the slug spec-2026-09-21-entra-hold-and-deny - a second branch
    beside the real one, whose first symptom is a deploy that ships nothing."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        env = {"AGENT_ORCHESTRATION_HOME": os.path.join(tmp, "aohome")}
        root = os.path.join(tmp, "bus")
        for path, want in {
            "SPEC-2026-09-21-entra-hold-and-deny.md": "entra-hold-and-deny",
            "docs/SPEC-2026-09-21-entra-hold-and-deny.md": "entra-hold-and-deny",
            "docs/specs/entra-hold-and-deny-spec.md": "entra-hold-and-deny",
            "2026-09-18-multi-pipeline-engine.md": "multi-pipeline-engine",
            "RFC-2026-01-02-token-rotation.md": "token-rotation",
        }.items():
            got = run(root, "slug", "--spec", path, env=env).strip()
            assert got == want, f"{path} derived {got!r}, expected {want!r}"


def a_later_wave_lands_on_the_same_branch():
    """S52 - section 3.3, and the contract derive_slug's own docstring states: a later
    wave re-derives the slug and must land on the same string. The old rule suffixed on
    ANY collision with a live workstream, so wave 2 silently became <slug>-2 - a second
    branch in every repo, and a finish that merges the wrong half. The spec path decides:
    same document attaches, a different document that derives the same name is a real
    collision, and a bus too old to say stops rather than guessing a branch."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        home = os.path.join(tmp, "aohome")
        env = {"AGENT_ORCHESTRATION_HOME": home}
        docs = os.path.join(tmp, "docs")
        os.makedirs(docs, exist_ok=True)
        spec = os.path.join(docs, "auth-v2.md")
        open(spec, "w", encoding="utf-8").write("# spec\n")

        root = os.path.join(home, "pipelines", "auth-v2", "pipeline")
        run(root, "init", "--slug", "auth-v2", "--spec", spec,
            "--feature", "Auth v2", env=env)
        rec = json.loads(open(os.path.join(root, "run.json"), encoding="utf-8").read())
        assert rec.get("specPath"), "init did not record which spec the workstream came from"

        assert run(root, "slug", "--spec", spec, env=env).strip() == "auth-v2", \
            "a wave of the same document must attach to the same slug, not suffix"

        other = os.path.join(tmp, "archive")
        os.makedirs(other, exist_ok=True)
        other_spec = os.path.join(other, "auth-v2.md")
        open(other_spec, "w", encoding="utf-8").write("# different feature\n")
        assert run(root, "slug", "--spec", other_spec, env=env).strip() == "auth-v2-2", \
            "a different document deriving the same name is a real collision"

        # A bus from before specPath existed cannot be told apart. Suffixing stays the
        # default there - two different live workstreams must not share a branch - but it
        # must not happen silently, and --wave has to be offered as the way to attach.
        legacy = os.path.join(home, "pipelines", "legacy-ws", "pipeline")
        run(legacy, "init", "--slug", "legacy-ws", "--feature", "Legacy", env=env)
        lspec = os.path.join(docs, "legacy-ws.md")
        open(lspec, "w", encoding="utf-8").write("# spec\n")
        out = run(legacy, "slug", "--spec", lspec, env=env).strip()
        assert out == "legacy-ws-2", \
            f"an undecidable collision must still suffix, exactly as it always did: {out!r}"
        assert run(legacy, "slug", "--spec", lspec, "--wave", env=env).strip() == "legacy-ws", \
            "--wave must attach to the live workstream instead of suffixing"


def an_inherited_failure_needs_evidence_not_a_smaller_number():
    """S48 - qa-check used to fail on any non-zero `failed`, so a correct run that
    inherited two pre-existing reds was gated red anyway, and the cheapest way to green it
    was to edit the number down. That is an incentive to falsify the record, not a
    friction. An inherited failure can be declared - with evidence - and anything beyond
    the declared ones is new by definition."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        root = os.path.join(tmp, "pipeline")
        run(root, "init", "--feature", "Baseline reds")
        run(root, "task", "add", "--id", "T1", "--title", "only task")
        run(root, "task", "update", "--id", "T1", "--status", "done")
        os.makedirs(os.path.join(root, "review"), exist_ok=True)
        os.makedirs(os.path.join(root, "test"), exist_ok=True)
        rev = os.path.join(root, "review", "review.json")
        res = os.path.join(root, "test", "results.json")
        open(rev, "w", encoding="utf-8").write(json.dumps({"findings": []}))

        def results(payload):
            open(res, "w", encoding="utf-8").write(json.dumps(payload))

        results({"failed": 2})
        out = run(root, "qa-check", expect=1)
        assert "failing test" in out, out

        # Declared, with proof, and nothing else red: the gate is green.
        results({"failed": 2, "baselineFailures": [
            {"test": "a", "evidence": "fails on base 1cbf13f"},
            {"test": "b", "evidence": "fails on base 1cbf13f"}]})
        run(root, "qa-check")

        # One more red than declared is new, whatever the declarations say.
        results({"failed": 3, "baselineFailures": [
            {"test": "a", "evidence": "fails on base 1cbf13f"},
            {"test": "b", "evidence": "fails on base 1cbf13f"}]})
        out = run(root, "qa-check", expect=1)
        assert "1 new failing test" in out, out

        # A declaration without evidence is a claim, not a baseline.
        results({"failed": 1, "baselineFailures": [{"test": "a"}]})
        out = run(root, "qa-check", expect=1)
        assert "no evidence" in out, out


def heartbeat_keeps_a_long_command_from_looking_dead():
    """S47 - the watchdog kills an agent after ~600s of silent output, and a ten-minute
    build is silent for its whole duration. Five agents across two estates have died that
    way. The wrapper has to do three things or it is not worth running: tick while the
    command lives, exit with the command's own code, and break a lock whose owner is gone
    rather than waiting out an age-based timeout - a hard kill never runs a shell trap."""
    hb = os.path.join(os.path.dirname(PIPE), "heartbeat.py")
    assert os.path.isfile(hb), "scripts/heartbeat.py is missing"

    def hbrun(*args):
        r = subprocess.run([sys.executable, hb, *args], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=120)
        return r.returncode, r.stdout + r.stderr

    code, _ = hbrun("--", sys.executable, "-c", "import sys; sys.exit(7)")
    assert code == 7, f"the wrapped command's exit code must survive; got {code}"

    code, out = hbrun("--tick", "1", "--",
                      sys.executable, "-c", "import time; time.sleep(3)")
    assert code == 0, code
    assert "[heartbeat]" in out, \
        f"nothing was printed while the command ran - the stream stays silent:\n{out}"

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        # A lock whose owner is long gone must not cost the next build its timeout.
        locks = os.path.join(os.path.expanduser("~"), ".agent-orchestration", "locks")
        os.makedirs(locks, exist_ok=True)
        name = "test-" + os.path.basename(tmp)
        lock = os.path.join(locks, name + ".lock")
        open(lock, "w", encoding="utf-8").write("999999")
        try:
            code, out = hbrun("--lock", name, "--", sys.executable, "-c", "pass")
            assert code == 0, f"a dead owner's lock blocked the run: {out}"
            assert "breaking" in out, f"the steal must say so:\n{out}"
            assert not os.path.exists(lock), "the lock was not released on exit"
        finally:
            if os.path.exists(lock):
                os.unlink(lock)


def a_plan_the_pipeline_cannot_use_is_refused():
    """S55 - P4. plan.json was the one bus artefact pipe.py never wrote and never checked,
    and it is what everything downstream reads: tasks, criteriaRef, services, criteria.
    The finalize gate asked the orchestrator to 'sanity-check' it, which is an LLM
    judgement standing where a check belongs - and two real defects came through it, a
    criteriaRef written as an array index and criteria nothing could join to a task."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        root = os.path.join(tmp, "pipeline")
        run(root, "init", "--feature", "Plan validation")
        plan = os.path.join(root, "plan.json")

        out = run(root, "validate-plan", expect=1)
        assert "no plan" in out, out

        def write(obj):
            with open(plan, "w", encoding="utf-8") as fh:
                json.dump(obj, fh)

        good = {"services": [{"name": "api", "dependsOnServices": []}],
                "acceptanceCriteria": ["AC1 - first", "AC2 - second"],
                "tasks": [{"id": "T1", "title": "a", "service": "api", "criteriaRef": ["AC1"],
                           "size": "S", "complexity": "low", "minutes": 5},
                          {"id": "T2", "title": "b", "service": "api", "criteriaRef": ["AC2"],
                           "size": "M", "complexity": "low", "minutes": 10}]}
        write(good)
        run(root, "validate-plan")

        # An index silently re-points the moment the criteria list is reordered.
        bad = json.loads(json.dumps(good))
        bad["tasks"][0]["criteriaRef"] = [0]
        write(bad)
        assert "by index" in run(root, "validate-plan", expect=1)

        bad = json.loads(json.dumps(good))
        bad["tasks"][1]["id"] = "T1"
        write(bad)
        assert "duplicate task id" in run(root, "validate-plan", expect=1)

        bad = json.loads(json.dumps(good))
        bad["tasks"][0]["service"] = "nope"
        write(bad)
        assert "not in services[]" in run(root, "validate-plan", expect=1)

        bad = json.loads(json.dumps(good))
        bad["tasks"] = bad["tasks"][:1]
        write(bad)
        assert "no task implements AC2" in run(root, "validate-plan", expect=1)


def a_run_carries_its_own_estimate_and_closes_itself():
    """S69 - ADR-0006. The planner sizes each task once; everything after is arithmetic on
    the bus. Covers the band check, the dependency chain, the work/waiting/paused clock,
    the run phase following its services, qa-check completing the work, and the human's
    one stamp after it."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        root = os.path.join(tmp, "pipeline")
        run(root, "init", "--feature", "Estimated")
        task = lambda i, svc, size, cx, mins, **kw: {
            "id": i, "title": i, "service": svc, "criteriaRef": ["AC1"],
            "size": size, "complexity": cx, "minutes": mins, **kw}
        plan = {"services": [{"name": "api", "dependsOnServices": []},
                             {"name": "web", "dependsOnServices": ["api"]}],
                "acceptanceCriteria": ["AC1 - it works"],
                "tasks": [task("T1", "api", "M", "low", 10),
                          task("T2", "api", "L", "high", 60, reason="contract and migration"),
                          task("T3", "web", "S", "low", 5)]}
        put = lambda obj: write(os.path.join(root, "plan.json"), json.dumps(obj))
        put(plan)
        run(root, "validate-plan")

        bad = json.loads(json.dumps(plan)); bad["tasks"][0]["minutes"] = 40
        put(bad)
        assert "outside the M/low band" in run(root, "validate-plan", expect=1)
        bad = json.loads(json.dumps(plan)); del bad["tasks"][1]["reason"]
        put(bad)
        assert "gives no 'reason'" in run(root, "validate-plan", expect=1)
        put(plan)

        for t in plan["tasks"]:
            run(root, "task", "add", "--id", t["id"], "--title", t["id"], "--service", t["service"])
        run(root, "phase", "implement")
        eta = read_run(root)["eta"]
        # web waits on api, so implement is the chain 70 + 5, not the longer of the two.
        assert eta["phases"] == {"spec": 5, "plan": 14, "implement": 75, "test": 110,
                                 "review": 15, "qa": 15}, eta
        assert eta["leftMin"] == 75 + 110 + 15 + 15, eta
        assert eta["likelyMin"] > eta["leftMin"], eta

        run(root, "task", "update", "--id", "T1", "--status", "in_progress")
        run(root, "task", "update", "--id", "T1", "--status", "done")
        t1 = read_json(os.path.join(root, "tasks.json"))["tasks"][0]
        assert t1.get("startedAt") and t1.get("doneAt"), t1
        assert read_run(root)["eta"]["leftMin"] == 65 + 110 + 15 + 15, "a done task leaves the estimate"

        # The clock: a long silence while running is a pause; time at a gate is waiting.
        def backdate(minutes, status):
            r = read_run(root)
            r["clock"]["at"] = time.strftime(
                "%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(time.time() - minutes * 60))
            r["clock"]["status"] = status
            write(os.path.join(root, "run.json"), json.dumps(r))
        backdate(40, "running")
        run(root, "agent", "coder")
        backdate(7, "awaiting_approval")
        run(root, "agent", "coder")
        backdate(6, "running")
        run(root, "agent", "coder")
        c = read_run(root)["clock"]
        assert 39 < c["pausedMin"] < 41 and 6.9 < c["waitMin"] < 7.2, c
        assert 5.9 < c["work"]["implement"] < 6.5, c
        assert "work left" in run(root, "eta")

        # The run's phase follows its services once all of them have moved on.
        run(root, "svc", "--name", "api", "--phase", "review")
        assert read_run(root)["phase"] == "implement", "one service ahead moves nothing"
        run(root, "svc", "--name", "web", "--phase", "test")
        assert read_run(root)["phase"] == "test", read_run(root)["phase"]

        assert "not completed yet" in run(root, "complete", expect=1)
        clean = os.path.join(tmp, "clean.json")
        write(clean, json.dumps({"recommendation": "approve", "findings": []}))
        for svc in ("api", "web"):
            os.makedirs(os.path.join(root, "services", svc, "test"), exist_ok=True)
            write(os.path.join(root, "services", svc, "test", "results.json"),
                  json.dumps({"passed": 2, "failed": 0}))
            run(root, "review", "--from", clean, "--service", svc)
        for i in ("T2", "T3"):
            run(root, "task", "update", "--id", i, "--status", "done")
        assert read_run(root)["status"] == "running"
        out = run(root, "qa-check", "--service", "api")
        assert read_run(root)["status"] == "running", "one lane green is not the run"
        out = run(root, "qa-check")
        r = read_run(root)
        assert "work completed" in out and r["status"] == "done" and r["phase"] == "done", out
        assert r["workCompletedAt"] and r["eta"]["leftMin"] == 0, r
        assert r["humanSteps"][0] == "Review and merge the feature branch in api, web", r["humanSteps"]
        assert len(r["humanSteps"]) == 3, "no worktrees, so there is nothing for finish to close"

        run(root, "complete")
        stamp = read_json(os.path.join(tmp, "completed.json"))
        assert stamp["runId"] == r["runId"] and stamp["by"] == "terminal", stamp


def the_estimate_clock_and_close_hold_at_their_edges():
    """S70 - ADR-0006. The edges S69 does not reach: the band message names the task,
    independent services cost the longer, a gate is waiting and not work, the 15-minute line
    between work and a pause, the run phase never jumping to done, the steps qa-check
    prints, the `eta` command, and a plan with no estimate showing none and erroring on
    nothing."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        root = os.path.join(tmp, "pipeline")
        run(root, "init", "--feature", "Edges")
        task = lambda i, svc, size, mins: {"id": i, "title": i, "service": svc,
            "criteriaRef": ["AC1"], "size": size, "complexity": "low", "minutes": mins}
        plan = {"services": [{"name": "api", "dependsOnServices": []},
                             {"name": "web", "dependsOnServices": []}],
                "acceptanceCriteria": ["AC1 - it works"],
                "tasks": [task("T1", "api", "M", 10), task("T2", "web", "S", 5)]}
        put = lambda obj: write(os.path.join(root, "plan.json"), json.dumps(obj))
        put(plan)
        run(root, "validate-plan")
        bad = json.loads(json.dumps(plan)); bad["tasks"][0]["minutes"] = 40
        put(bad)
        out = run(root, "validate-plan", expect=1)
        assert "'T1'" in out and "M/low band" in out, out          # AC1: the task and the band
        put(plan)
        for t in plan["tasks"]:
            run(root, "task", "add", "--id", t["id"], "--title", t["id"], "--service", t["service"])
        run(root, "phase", "implement")
        eta = read_run(root)["eta"]
        assert eta["phases"]["implement"] == 10, eta                # AC3: the longer, not 15

        def backdate(minutes, status):
            r = read_run(root)
            r["clock"]["at"] = time.strftime(
                "%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(time.time() - minutes * 60))
            r["clock"]["status"] = status
            write(os.path.join(root, "run.json"), json.dumps(r))

        run(root, "set-status", "awaiting_approval")                # AC4: a gate is waiting
        left = read_run(root)["eta"]["leftMin"]
        backdate(10, "awaiting_approval")
        run(root, "agent", "coder")
        r = read_run(root)
        assert 9.9 < r["clock"]["waitMin"] < 10.2 and r["eta"]["leftMin"] == left, r["clock"]
        run(root, "set-status", "running")

        backdate(14.5, "running")                                   # AC5: the 15-minute line
        run(root, "agent", "coder")
        c = read_run(root)["clock"]
        assert c["pausedMin"] == 0 and 14.4 < c["work"]["implement"] < 14.7, c
        backdate(15.5, "running")
        run(root, "agent", "coder")
        c = read_run(root)["clock"]
        assert 15.4 < c["pausedMin"] < 15.7 and c["work"]["implement"] < 14.7, c

        out = run(root, "eta")                                      # AC13: every line
        for word in ("work left", "expected", "likely by", "waited on you", "total",
                     "spec", "plan", "implement", "test", "review", "qa"):
            assert word in out, f"`eta` prints no '{word}':\n{out}"

        run(root, "svc", "--name", "api", "--phase", "done")        # AC6: forward, never done
        run(root, "svc", "--name", "web", "--phase", "done")
        r = read_run(root)
        assert r["phase"] == "qa" and r["status"] == "running", (r["phase"], r["status"])

        clean = os.path.join(tmp, "clean.json")                     # AC7: the steps are printed
        write(clean, json.dumps({"recommendation": "approve", "findings": []}))
        for svc in ("api", "web"):
            os.makedirs(os.path.join(root, "services", svc, "test"), exist_ok=True)
            write(os.path.join(root, "services", svc, "test", "results.json"),
                  json.dumps({"passed": 2, "failed": 0}))
            run(root, "review", "--from", clean, "--service", svc)
        for i in ("T1", "T2"):
            run(root, "task", "update", "--id", i, "--status", "done")
        out = run(root, "qa-check", cwd=tmp)
        steps = read_run(root)["humanSteps"]
        assert steps and all(s in out for s in steps), out

        old = os.path.join(tmp, "old", "pipeline")                  # AC12: no estimate
        run(old, "init", "--feature", "Old")
        write(os.path.join(old, "plan.json"), json.dumps(plan))
        run(old, "phase", "implement")
        assert "eta" in read_run(old)
        no_minutes = json.loads(json.dumps(plan))
        for t in no_minutes["tasks"]:
            del t["minutes"]
        write(os.path.join(old, "plan.json"), json.dumps(no_minutes))
        run(old, "agent", "coder")
        assert "eta" not in read_run(old), "a re-plan without estimates kept the old one"
        assert "no estimate" in run(old, "eta"), "`eta` on an old plan erred or said nothing"


def a_project_names_its_own_human_steps():
    """S71 - the steps after "work completed" come from the project's config when it names
    them, filled in with the run's own slug, branch and services. A malformed value is
    refused by `config` and ignored by the run - the defaults stand, never an empty list."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        proj = os.path.join(tmp, "proj")
        os.makedirs(os.path.join(proj, "api"))
        cfg = os.path.join(proj, "agent-orchestration.config.json")

        def steps_of(n, steps):
            write(cfg, json.dumps({"services": [{"name": "api", "path": "api"}], "humanSteps": steps}))
            root = os.path.join(tmp, f"b{n}", "pipeline")
            run(root, "init", "--feature", "Steps", "--slug", "steps")
            run(root, "svc", "--name", "api", "--phase", "implement")
            run(root, "phase", "done", cwd=proj)
            return read_run(root)["humanSteps"]

        assert steps_of(1, ["Ship {slug} from {branch}", "Tell people about {services}"]) == \
            ["Ship steps from feature/steps", "Tell people about api"]
        for n, bad in enumerate(("deploy", [""], ["ok", "  "]), 2):
            write(cfg, json.dumps({"services": [{"name": "api", "path": "api"}], "humanSteps": bad}))
            assert "humanSteps" in run(os.path.join(tmp, "x"), "config", cwd=proj, expect=1)
            assert len(steps_of(n, bad)) == 3, "a malformed humanSteps replaced the defaults"


def a_write_survives_a_reader_holding_the_file():
    """S76 - on Windows os.replace raises PermissionError while a dashboard has run.json
    open, and every event now rewrites run.json. One refusal must not crash the caller;
    a refusal that never lifts must still fail, and leave no temp file behind."""
    pipe = import_pipe()
    real = os.replace
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        target = os.path.join(tmp, "run.json")
        calls = []

        def flaky(src, dst):
            calls.append(src)
            if len(calls) == 1:
                raise PermissionError(5, "Access is denied")
            return real(src, dst)

        def never(src, dst):
            raise PermissionError(5, "Access is denied")
        try:
            os.replace = flaky
            pipe.atomic_write(target, "landed")
            assert open(target, encoding="utf-8").read() == "landed" and len(calls) == 2, calls
            os.replace = never
            try:
                pipe.atomic_write(target, "refused")
                raise AssertionError("a permanent refusal was swallowed")
            except PermissionError:
                pass
        finally:
            os.replace = real
        assert os.listdir(tmp) == ["run.json"], os.listdir(tmp)


def the_final_button_and_the_payload_are_tested():
    """S72 - POST /api/complete is the hall's last door: it writes completed.json beside the
    bus, so it resolves a slug by identity, refuses a run that is not done, and stamps the
    run it saw, so a later wave reads as not completed. The same hall payload carries the
    estimate and the clock, and nothing for a plan that has none."""
    if not shutil.which("node"):
        print("SKIP S72 - no node on PATH; the /api/complete endpoint was not exercised")
        return
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        home = os.path.join(tmp, "aohome")
        env = {"AGENT_ORCHESTRATION_HOME": home}
        root = os.path.join(home, "pipelines", "shipped", "pipeline")
        old = os.path.join(home, "pipelines", "old", "pipeline")
        run(root, "init", "--feature", "Shipped", "--slug", "shipped", env=env)
        run(old, "init", "--feature", "Old", "--slug", "old", env=env)
        task = {"id": "T1", "title": "t", "service": "api", "criteriaRef": ["AC1"],
                "size": "M", "complexity": "low", "minutes": 10}
        plan = {"services": [{"name": "api"}], "acceptanceCriteria": ["AC1 - x"], "tasks": [task]}
        write(os.path.join(root, "plan.json"), json.dumps(plan))
        del task["minutes"]
        write(os.path.join(old, "plan.json"), json.dumps(plan))
        run(root, "phase", "implement", env=env)
        run(old, "phase", "implement", env=env)
        stamp = os.path.join(home, "pipelines", "shipped", "completed.json")

        def card(port, slug):
            code, body = http_json(port, "/api/hall")
            assert code == 200, (code, body[:200])
            return [p for p in json.loads(body)["pipelines"] if p["slug"] == slug][0]

        with Server(home) as s:
            p = card(s.port, "shipped")
            assert set(p["eta"]) >= {"phases", "totalMin", "leftMin", "likelyMin"}, p["eta"]
            assert set(p["clock"]) >= {"at", "work", "waitMin", "pausedMin"}, p["clock"]
            for k in ("branch", "workCompletedAt", "humanSteps", "completed"):
                assert k in p, f"the hall payload carries no '{k}'"
            assert card(s.port, "old")["eta"] is None, "a plan with no minutes carries an estimate"

            for slug in ("no-such-run", "../../etc"):
                code, body = http_json(s.port, "/api/complete", {"slug": slug})
                assert code == 404, (slug, code, body)
            code, body = http_json(s.port, "/api/complete", {"slug": "shipped"})
            assert code == 409 and not os.path.exists(stamp), (code, body)

            run(root, "phase", "done", env=env)
            assert http_json(s.port, "/api/complete", {"slug": "shipped"})[0] == 200
            done = read_json(stamp)
            assert done["runId"] == read_run(root)["runId"] and done["by"] == "browser", done
            assert card(s.port, "shipped")["completed"], "/api/hall does not report it completed"

            data = read_run(root)
            data["runId"] = "run-a-later-wave"
            write(os.path.join(root, "run.json"), json.dumps(data, indent=2))
            assert card(s.port, "shipped")["completed"] is None, "a stamp outlived its run"


def the_write_endpoints_refuse_cross_site_posts():
    """S72b - a text/plain POST, or one from a foreign Origin, is refused before any write."""
    if not shutil.which("node"):
        print("SKIP S72b - no node on PATH")
        return
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        home = os.path.join(tmp, "aohome")
        env = {"AGENT_ORCHESTRATION_HOME": home}
        root = os.path.join(home, "pipelines", "shipped", "pipeline")
        run(root, "init", "--feature", "Shipped", "--slug", "shipped", env=env)
        run(root, "phase", "done", env=env)
        stamp = os.path.join(home, "pipelines", "shipped", "completed.json")
        with Server(home) as s:
            def post(headers):
                req = urllib.request.Request(f"http://127.0.0.1:{s.port}/api/complete",
                                             data=b'{"slug":"shipped"}', method="POST", headers=headers)
                try:
                    with urllib.request.urlopen(req, timeout=5) as r:
                        return r.status
                except urllib.error.HTTPError as e:
                    return e.code
            assert post({"Content-Type": "text/plain"}) == 415
            assert post({"Content-Type": "application/json", "Origin": "http://evil.example"}) == 403
            assert not os.path.exists(stamp), "a refused POST wrote the stamp"
            assert post({"Content-Type": "application/json",
                         "Origin": f"http://localhost:{s.port}"}) == 200


def test_results_are_written_through_a_check():
    """S56 - results.json was the last artefact written free-hand, and qa-check gates the
    run on it: the one file that decides whether work ships had no shape check at all. A
    count with no failures behind it is not a report the coder can act on."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        root = os.path.join(tmp, "pipeline")
        run(root, "init", "--feature", "Results validation")
        src = os.path.join(tmp, "r.json")

        def write(obj):
            with open(src, "w", encoding="utf-8") as fh:
                json.dump(obj, fh)

        write({"total": 10, "passed": 8, "failed": 1, "failures": []})
        assert "does not equal total" in run(root, "results", "--from", src, expect=1)

        write({"total": 2, "passed": 1, "failed": 1, "failures": []})
        assert "'failures' is empty" in run(root, "results", "--from", src, expect=1)

        write({"total": 2, "passed": 1, "failed": 1,
               "failures": [{"scenario": "S1", "expected": "x"}]})
        assert "no 'actual'" in run(root, "results", "--from", src, expect=1)

        write({"total": 1, "passed": 0, "failed": 1,
               "failures": [{"scenario": "S1", "expected": "x", "actual": "y"}],
               "baselineFailures": [{"test": "S1"}]})
        assert "no evidence" in run(root, "results", "--from", src, expect=1)

        write({"iteration": 1, "total": 2, "passed": 2, "failed": 0, "failures": []})
        run(root, "results", "--from", src)
        written = os.path.join(root, "test", "results.json")
        assert os.path.isfile(written), "a valid payload was not persisted"
        assert json.loads(open(written, encoding="utf-8").read())["total"] == 2


def the_fix_budget_is_counted_where_it_is_kept():
    """S57 - P1. The budget was a number the orchestrator wrote and then trusted itself to
    compare against max; nothing in code stopped a miscount from looping past five. The
    count belongs to the state, and the answer the caller needs is `blocked`, not a number
    it has to reason about."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        root = os.path.join(tmp, "pipeline")
        run(root, "init", "--feature", "Loop budget")
        seen = []
        for _ in range(6):
            out = run(root, "svc", "--name", "api", "--bump-loop", "--loop-max", "3")
            svc = json.loads(out)["api"]
            seen.append((svc["loop"]["count"], svc["blocked"]))
        assert [c for c, _ in seen] == [1, 2, 3, 4, 5, 6], seen
        assert [b for _, b in seen] == [False, False, True, True, True, True], \
            f"blocked must latch at max and stay latched: {seen}"


def no_tracked_source_carries_a_byte_order_mark():
    """S54 - PowerShell's `Set-Content -Encoding utf8` writes a UTF-8 BOM, and this repo is
    edited from PowerShell. A BOM at the top of pipe.py is invisible in every editor and
    breaks anything that reads the file as plain utf-8 - ast.parse refuses it outright.
    Five tracked files picked one up in a single afternoon before this caught it."""
    bom = b"\xef\xbb\xbf"
    bad = []
    for dirpath, dirnames, files in os.walk(REPO):
        dirnames[:] = [d for d in dirnames if d not in (".git", "node_modules", "pipeline")]
        for name in files:
            if not name.endswith((".py", ".md", ".js", ".html", ".json")):
                continue
            p = os.path.join(dirpath, name)
            with open(p, "rb") as fh:
                if fh.read(3) == bom:
                    bad.append(os.path.relpath(p, REPO))
    assert not bad, ("these carry a UTF-8 BOM; rewrite them without one "
                     f"(PowerShell: -Encoding utf8NoBOM, or Python): {sorted(bad)}")


SUPERPOWERS_PIN = "7.0.0"          # ADR-0002. Bump deliberately, never incidentally.


def superpowers_skills():
    """The skill ids the installed superpowers actually ships, or None if it is absent."""
    base = os.path.join(os.path.expanduser("~"), ".claude", "plugins", "cache",
                        "claude-plugins-official", "superpowers", SUPERPOWERS_PIN, "skills")
    if not os.path.isdir(base):
        return None
    return {d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d))}


def every_agent_names_a_skill_that_exists():
    """S53 - ADR-0002. The binding of a phase to a framework skill is the kind of thing
    that rots in prose: the runbook carried 'if superpowers is installed, prefer delegating
    to it' for weeks and no agent ever invoked anything. A named skill that does not exist
    is the same failure as a command named in an agent file but missing from pipe.py's
    parser, and is caught the same way. Skips - never fails - when superpowers is absent,
    because the pipeline still runs each phase natively without it."""
    bound = {}
    for name in ("planner", "coder", "tester", "reviewer", "operator"):
        path = os.path.join(REPO, "agents", name + ".md")
        if not os.path.isfile(path):
            continue
        src = open(path, encoding="utf-8").read()
        assert "## Framework" in src, f"agents/{name}.md names no framework skill (ADR-0002)"
        found = re.findall(r"`(superpowers:[a-z-]+)`", src)
        bound[name] = set(found)

    assert bound.get("planner"), "the planner is bound to no superpowers skill"
    assert bound.get("tester"), "the tester is bound to no superpowers skill"

    have = superpowers_skills()
    if have is None:
        print(f"SKIP S53 - superpowers {SUPERPOWERS_PIN} is not installed; "
              f"bindings were checked for shape only")
        return

    for agent, skills in bound.items():
        for s in skills:
            short = s.split(":", 1)[1]
            assert short in have, \
                f"agents/{agent}.md invokes '{s}', which superpowers {SUPERPOWERS_PIN} " \
                f"does not ship. Known: {sorted(have)}"

    # The version is pinned because an upstream change alters how every agent works, and
    # this project has been served a stale cached build three times without noticing.
    root = os.path.dirname(os.path.dirname(
        os.path.join(os.path.expanduser("~"), ".claude", "plugins", "cache",
                     "claude-plugins-official", "superpowers", SUPERPOWERS_PIN, "x")))
    installed = sorted(d for d in os.listdir(root)
                       if re.fullmatch(r"\d+\.\d+\.\d+", d))
    assert installed and installed[-1] == SUPERPOWERS_PIN, \
        (f"superpowers {installed[-1] if installed else 'none'} is installed but ADR-0002 "
         f"pins {SUPERPOWERS_PIN}. Re-read the changed skills, then bump the pin.")


def the_runbook_fits_what_survives_a_compaction():
    """S61 - superpowers 7.0.1 found that a compaction re-attaches a skill cut off at 20,000
    characters, and a session that lost its fix-loop cap ran 18 rounds. The runbook is read
    as a file, not a skill, so it gets no re-attach at all: what keeps its rules in front of
    the orchestrator is that each part is small enough to re-read at the step that needs it.
    So every part stays under the limit, every part is named by the core that sends you to
    it, and none carries the mojibake that once doubled the bytes of every dash."""
    core = os.path.join(REPO, "docs", "orchestration-runbook.md")
    parts = sorted(glob.glob(os.path.join(REPO, "docs", "runbook", "*.md")))
    assert parts, "docs/runbook/ is empty - the per-path parts are gone"
    core_text = open(core, encoding="utf-8").read()
    for path in [core] + parts:
        text = open(path, encoding="utf-8").read()
        rel = os.path.relpath(path, REPO).replace(os.sep, "/")
        assert len(text) < 20000, f"{rel} is {len(text)} chars; split it below 20,000"
        assert not re.search("â€|Â§", text),             f"{rel} carries mojibake (a UTF-8 dash read as cp1252); rewrite it as UTF-8"
        if path != core:
            assert "docs/runbook/" + os.path.basename(path) in core_text,                 f"the runbook never sends the orchestrator to {rel}"


def a_plan_gate_card_carries_the_plan():
    """S62. Approving from the hall used to mean opening the board first, because a gate
    card showed only that a plan existed. /api/hall now carries a brief of plan.json - its
    size, approach and tasks - for a run waiting at its plan gate, and for nothing else, so
    every other card stays as small as it was."""
    if not shutil.which("node"):
        print("SKIP S62 - no node on PATH; the hall payload was not exercised")
        return
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        home = os.path.join(tmp, "aohome")
        env = {"AGENT_ORCHESTRATION_HOME": home}
        gated = os.path.join(home, "pipelines", "gated", "pipeline")
        moving = os.path.join(home, "pipelines", "moving", "pipeline")
        run(gated, "init", "--feature", "Gated", "--slug", "gated", env=env)
        run(moving, "init", "--feature", "Moving", "--slug", "moving", env=env)
        plan = {"approach": "a" * 900, "services": [{"name": "api"}, {"name": "web"}],
                "acceptanceCriteria": [{"id": "AC1", "text": "x"}, {"id": "AC2", "text": "y"}],
                "tasks": [{"id": f"T{i}", "service": "api", "title": "t" * 300,
                           **({"complexity": "high"} if i < 2 else {})} for i in range(40)],
                "risks": ["r"], "questions": []}
        for root in (gated, moving):
            write(os.path.join(root, "plan.json"), json.dumps(plan))
        run(gated, "phase", "plan", env=env)
        run(gated, "set-status", "awaiting_approval", env=env)
        run(moving, "phase", "implement", env=env)

        with Server(home) as s:
            code, body = http_json(s.port, "/api/hall")
            assert code == 200, (code, body[:200])
            by = {p["slug"]: p for p in json.loads(body)["pipelines"]}
            b = by["gated"]["plan"]
            assert b, "a run at its plan gate carries no plan brief"
            assert b["taskCount"] == 40 and len(b["tasks"]) == 30, "the task list is not capped"
            assert b["high"] == 2, "the brief does not count high-complexity tasks"
            assert b["services"] == ["api", "web"] and b["criteria"] == 2 and b["risks"] == 1
            assert len(b["approach"]) <= 400 and len(b["tasks"][0]["title"]) <= 140, \
                "the brief carries whole fields - a gate card would carry the plan file"
            assert by["moving"]["plan"] is None, "a running card carries a plan it does not show"


HOOKS = os.path.join(REPO, "hooks", "ao-hooks.js")


def hook(event, env):
    r = subprocess.run(["node", HOOKS], input=json.dumps(event), capture_output=True,
                       text=True, encoding="utf-8", env={**os.environ, **env}, timeout=30)
    assert r.returncode == 0, f"the hook exited {r.returncode}: {r.stderr}"
    return json.loads(r.stdout) if r.stdout.strip() else None


def transcript(path, main_tokens, side_tokens=0):
    """A chat whose last main-thread reply carried main_tokens of context, and - after it -
    a subagent reply carrying side_tokens, which must not count against the chat."""
    def reply(n, side):
        return json.dumps({"type": "assistant", "isSidechain": side, "message": {"usage": {
            "input_tokens": 10, "cache_read_input_tokens": n - 110,
            "cache_creation_input_tokens": 50, "output_tokens": 50}}})
    write(path, "\n".join([json.dumps({"type": "user"}), reply(main_tokens, False),
                           reply(side_tokens or 1000, True)]) + "\n")


def ship_waits_for_a_fresh_chat_once():
    """S63 - ADR-0003. The orchestrator re-reads its whole chat on every turn, and a real
    run began in one already holding 492k tokens. /ship in a large chat is stopped once and
    runs when sent again; the model calling the skill itself cannot confirm on the person's
    behalf; a subagent's large context in the same transcript is not the chat's."""
    if not shutil.which("node"):
        print("SKIP S63 - no node on PATH; the /ship guard was not exercised")
        return
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        env = {"AO_HOOK_STATE": tmp}
        small, large = os.path.join(tmp, "small.jsonl"), os.path.join(tmp, "large.jsonl")
        transcript(small, 40000, side_tokens=600000)
        transcript(large, 492000)
        typed = lambda tr, sid, name="ship": {"hook_event_name": "UserPromptExpansion",
            "session_id": sid, "transcript_path": tr, "command_name": name,
            "command_args": "add a health endpoint", "prompt": f"/{name} add a health endpoint"}
        called = lambda tr, sid: {"hook_event_name": "PreToolUse", "session_id": sid,
            "transcript_path": tr, "tool_name": "Skill",
            "tool_input": {"skill": "agent-orchestration:ship"}}

        assert hook(typed(small, "s1"), env) is None, "a fresh chat was stopped"
        assert hook(typed(large, "s2", "deploy"), env) is None, "a command that is not /ship was stopped"
        out = hook(typed(large, "s2"), env)
        assert out and out.get("decision") == "block" and "492k" in out.get("reason", ""), out
        out = hook(called(large, "s2"), env)
        assert out and out["hookSpecificOutput"]["permissionDecision"] == "deny", \
            "the model confirmed a stopped /ship on the person's behalf"
        assert hook(typed(large, "s2"), env) is None, "sending /ship again did not run it"
        assert hook(called(large, "s2"), env) is None, "a typed confirmation did not reach the skill"
        out = hook(called(large, "s3"), env)
        assert out and out["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert hook(called(small, "s4"), env) is None


def a_usage_limit_reads_as_a_pause():
    """S64 - ADR-0003. During a usage limit no agent writes to any bus, and the hall called
    every running team dead. The hook marks the pause; the hall carries it until Claude Code
    resumes or any bus moves again, and says when the reset is waiting on the person."""
    if not shutil.which("node"):
        print("SKIP S64 - no node on PATH; the usage-limit pause was not exercised")
        return
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        home = os.path.join(tmp, "aohome")
        env = {"AGENT_ORCHESTRATION_HOME": home}
        root = os.path.join(home, "pipelines", "paused", "pipeline")
        run(root, "init", "--feature", "Paused", "--slug", "paused", env=env)
        marker = os.path.join(home, "usage-limit.json")
        limit = lambda port: json.loads(http_json(port, "/api/hall")[1])["limit"]

        with Server(home) as s:
            assert limit(s.port) is None
            hook({"hook_event_name": "StopFailure", "error": "overloaded"}, env)
            assert not os.path.exists(marker), "an overload is not a usage limit"
            hook({"hook_event_name": "StopFailure", "error": "rate_limit"}, env)
            assert limit(s.port)["state"] == "waiting", "the hall does not carry the pause"
            hook({"hook_event_name": "Notification", "notification_type": "quota_auto_resume_stale"}, env)
            assert limit(s.port)["state"] == "needs-you"
            hook({"hook_event_name": "Notification", "notification_type": "quota_auto_resume_fired"}, env)
            assert not os.path.exists(marker) and limit(s.port) is None, "a resume left the pause up"

            hook({"hook_event_name": "StopFailure", "error": "rate_limit"}, env)
            time.sleep(1.1)
            run(root, "event", "--agent", "coder", "--type", "status", "--summary", "back", env=env)
            assert limit(s.port) is None, "a bus that moved again still reads as paused"


def the_next_coder_takes_at_most_two_ready_tasks():
    """S65 - ADR-0003. One coder that carried a whole service grew to 438k tokens. `next`
    hands the orchestrator at most --max tasks, in plan order, each with its dependencies
    done or earlier in the same batch; a dependency cycle is named, not looped on."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        root = os.path.join(tmp, "pipeline")
        run(root, "init", "--feature", "Batches")
        tasks = [{"id": "T1", "service": "api", "wave": 1},
                 {"id": "T2", "service": "api", "wave": 2, "dependsOn": ["T1"]},
                 {"id": "T3", "service": "api", "wave": 1},
                 {"id": "T4", "service": "web", "wave": 1, "dependsOn": ["T2"]},
                 {"id": "T5", "service": "api", "wave": 3, "dependsOn": ["T6"]},
                 {"id": "T6", "service": "api", "wave": 3, "dependsOn": ["T5"]}]
        write(os.path.join(root, "plan.json"), json.dumps({"tasks": tasks}))
        for task in tasks:
            run(root, "task", "add", "--id", task["id"], "--title", task["id"], "--service", task["service"])
        nxt = lambda *a: json.loads(run(root, "next", *a))

        assert nxt("--service", "api")["next"] == ["T1", "T3"], "plan order is wave, then position"
        assert nxt("--service", "api", "--max", "3")["next"] == ["T1", "T3", "T2"], \
            "a task whose dependency is earlier in the same batch was held back"
        assert nxt("--service", "web")["next"] == [], "T4 ran before the task it depends on"
        for done in ("T1", "T3", "T2"):
            run(root, "task", "update", "--id", done, "--status", "done")
        assert nxt("--service", "web")["next"] == ["T4"]
        stuck = nxt("--service", "api")
        assert stuck["next"] == [] and stuck["remaining"] == ["T5", "T6"], \
            f"a dependency cycle must surface as nothing to do with work left: {stuck}"


def every_role_runs_on_a_chosen_model():
    """S66 - ADR-0003. Without `model:` the orchestrator picked Opus or Sonnet run by run.
    Each agent names its model, the planner plans on Opus, and the plugin's hooks file
    points at a script that exists."""
    allowed = {"opus", "sonnet", "haiku", "fable", "inherit"}
    for name in ("planner", "coder", "tester", "reviewer", "operator"):
        src = open(os.path.join(REPO, "agents", name + ".md"), encoding="utf-8").read()
        head = src.split("\n---", 1)[0]
        m = re.search(r"^model:\s*(\S+)\s*$", head, re.M)
        assert m and m.group(1) in allowed, f"agents/{name}.md names no model (ADR-0003)"
        if name in ("planner", "reviewer"):
            assert m.group(1) == "opus",                 f"the {name} decides or judges the design; it runs on opus (ADR-0003)"
    cfg = json.load(open(os.path.join(REPO, "hooks", "hooks.json"), encoding="utf-8"))
    for event, groups in cfg["hooks"].items():
        for g in groups:
            for h in g["hooks"]:
                script = h["args"][0].replace("${CLAUDE_PLUGIN_ROOT}", REPO)
                assert os.path.isfile(script), f"{event} hook runs {script}, which does not exist"


def the_design_rules_and_their_fixes_stay_in_sync():
    """S67 - ADR-0004. The rule table, the fix recipes and the agents that use them are three
    files that must agree, which is how GTID-Vault's skills once described rules that did
    not exist. Every rule has a level and a recipe and every recipe a rule, the ids run
    D1..Dn with no gap, the planner, coder and reviewer each point at the table, and a
    review finding cannot cite a rule the table does not define."""
    base = os.path.join(REPO, "skills", "design-rules")
    skill = open(os.path.join(base, "SKILL.md"), encoding="utf-8").read()
    fixes = open(os.path.join(base, "FIXES.md"), encoding="utf-8").read()
    assert os.path.isfile(os.path.join(base, "LANGUAGES.md"))
    assert re.search(r"^name: design-rules$", skill, re.M), "the skill's name is not its folder"
    assert len(skill) < 20000, f"SKILL.md is {len(skill)} chars; keep it under 20,000"

    rows = re.findall(r"^\| (D\d+) \| (\w+) \|", skill, re.M)
    ids = [r for r, _ in rows]
    assert ids == [f"D{i}" for i in range(1, len(ids) + 1)], f"rule ids must run D1..Dn: {ids}"
    assert {lvl for _, lvl in rows} <= {"must", "should"}, "a rule's level is must or should"
    recipes = re.findall(r"^## (D\d+) — ", fixes, re.M)
    assert sorted(recipes, key=lambda r: int(r[1:])) == ids, \
        f"rules without a recipe: {sorted(set(ids) - set(recipes))}; " \
        f"recipes without a rule: {sorted(set(recipes) - set(ids))}"

    for name in ("planner", "coder", "reviewer"):
        src = open(os.path.join(REPO, "agents", name + ".md"), encoding="utf-8").read()
        assert "skills/design-rules/SKILL.md" in src, f"agents/{name}.md never points at the rules"
    assert "skills/design-rules/FIXES.md" in \
        open(os.path.join(REPO, "agents", "coder.md"), encoding="utf-8").read(), \
        "the coder is never told where a cited rule's fix lives"

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        root = os.path.join(tmp, "pipeline")
        run(root, "init", "--feature", "Cited")
        finding = lambda rule: {"recommendation": "changes-required", "findings": [
            {"severity": "blocking", "file": "src/a.ts", "line": 3, "note": "entity in the response",
             "planRef": "T1", "rule": rule}]}
        bad, good = os.path.join(tmp, "bad.json"), os.path.join(tmp, "good.json")
        write(bad, json.dumps(finding("D99")))
        write(good, json.dumps(finding("D7")))
        out = run(root, "review", "--from", bad, expect=1)
        assert "D99" in out, out
        run(root, "review", "--from", good)
        md = open(os.path.join(root, "review", "review.md"), encoding="utf-8").read()
        assert "[T1 · D7]" in md, "review.md does not show which rule a finding cites"


def scenarios_are_written_as_use_cases():
    """S68 - ADR-0005. Acceptance criteria and test scenarios are Gherkin in plain words so the
    person who asked can review them. The rule table runs T1..Tn, each with a level and a
    fix; the spec writers, planner, tester and reviewer all point at it; the tester's
    example traces scenarios to criteria by id, never by index (the defect validate-plan
    refuses in a plan); and a review may cite a T rule but not one that does not exist."""
    base = os.path.join(REPO, "skills", "test-scenarios")
    skill = open(os.path.join(base, "SKILL.md"), encoding="utf-8").read()
    for extra in ("PLAYWRIGHT.md", "RUNNERS.md"):
        assert os.path.isfile(os.path.join(base, extra)), f"test-scenarios/{extra} is missing"
    assert re.search(r"^name: test-scenarios$", skill, re.M)
    assert len(skill) < 20000, f"SKILL.md is {len(skill)} chars; keep it under 20,000"
    rows = re.findall(r"^\| (T\d+) \| (\w+) \|.*\| ([^|]+) \|$", skill, re.M)
    ids = [r for r, _, _ in rows]
    assert ids == [f"T{i}" for i in range(1, len(ids) + 1)], f"rule ids must run T1..Tn: {ids}"
    assert {lvl for _, lvl, _ in rows} <= {"must", "should"}
    assert all(fix.strip() for _, _, fix in rows), "a rule without a fix"

    for path in ("skills/ship/SKILL.md", "skills/ship-from-spec/SKILL.md", "agents/planner.md",
                 "agents/tester.md", "agents/reviewer.md"):
        src = open(os.path.join(REPO, path), encoding="utf-8").read()
        assert "skills/test-scenarios/SKILL.md" in src, f"{path} never points at the scenario rules"
    tester = open(os.path.join(REPO, "agents", "tester.md"), encoding="utf-8").read()
    assert '"criteriaRef": ["AC' in tester and '"criteriaRef": [0]' not in tester, \
        "the tester's example traces criteria by index"

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        root = os.path.join(tmp, "pipeline")
        run(root, "init", "--feature", "Worded")
        for rule, code in (("T2", 0), ("T99", 1)):
            src = os.path.join(tmp, rule + ".json")
            write(src, json.dumps({"recommendation": "approve-with-notes", "findings": [
                {"severity": "major", "file": "e2e/login.spec.ts", "note": "clicks in the wording",
                 "rule": rule}]}))
            run(root, "review", "--from", src, expect=code)


def the_workstream_card_shows_the_estimate():
    """S73 - AC4, AC9, AC12. The card's figures and rail, drawn by hall.html's own etcHTML()
    in node on fixtures: running shows the clock, left and waited; a gate holds the work
    left however long it waited; blocked says so; no estimate draws nothing; and the grid
    still seats three to a row."""
    if not shutil.which("node"):
        print("SKIP S73 - no node on PATH; the card's estimate was not drawn")
        return
    src = open(HALL_HTML, encoding="utf-8").read()
    esc = re.search(r"const esc=[^\n]*\n", src)
    est = re.search(r"const IDLE_MIN=.*?(?=\nfunction pillTxt)", src, re.S)
    assert esc and est, "hall.html no longer has esc ... IDLE_MIN .. doneHTML ahead of pillTxt"
    import datetime
    now = datetime.datetime.now(datetime.timezone.utc)
    iso = lambda m: (now - datetime.timedelta(minutes=m)).isoformat()
    eta = {"phases": {"plan": 5, "implement": 30, "test": 10}, "totalMin": 45, "leftMin": 30,
           "likelyMin": 40}
    base = lambda **k: dict({"slug": "x", "status": "running", "phase": "implement", "eta": eta,
        "clock": {"at": iso(1), "work": {"plan": 5, "implement": 2}, "waitMin": 0, "pausedMin": 0}}, **k)
    fx = {"run": base(),
          "gate": base(status="awaiting_approval", phase="plan",
                       clock={"at": iso(120), "work": {}, "waitMin": 3, "pausedMin": 0}),
          "block": base(status="blocked"),
          "old": {"slug": "x", "status": "running", "phase": "implement"}}
    js = (esc.group(0) + est.group(0) + "\nconst fx=" + json.dumps(fx) +
          ";\nconst o={};for(const k in fx) o[k]=etcHTML(fx[k]);console.log(JSON.stringify(o));")
    r = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, f"hall.html etcHTML() did not run:\n{r.stdout}{r.stderr}"
    out = json.loads(r.stdout)
    for want in ("Work completed at", "likely by", "Work left", "Waited on you"):
        assert want in out["run"], f"a running card lacks {want!r}"
    assert re.search(r"\d\d:\d\d", out["run"]), "the clock time is not a local HH:MM"
    flex = [int(x) for x in re.findall(r'class="sg" style="flex:(\d+)', out["run"])]
    assert flex == [5, 30, 10], f"one rail segment per phase, sized by its estimate: {flex}"
    for want in ("Ready if approved now", "Waiting on you", "and counting"):
        assert want in out["gate"], f"a gate card lacks {want!r}"
    assert '<div class="v sm">30m</div>' in out["gate"], \
        "the work left shrank while the run waited at a gate (AC4)"
    assert "Ready if unblocked now" in out["block"], "a blocked card does not say so"
    assert out["old"] == "", "a plan with no estimate drew something (AC12)"
    assert re.search(r"#hall\{display:grid;grid-template-columns:repeat\(3,minmax\(0,1fr\)\)", src), \
        "the hall is not three cards to a row"
    assert "${etcHTML(p)}" in src, "card() does not draw the estimate"


def the_board_draws_the_lanes_the_inspector_and_the_time_band():
    """S74 - AC11, AC12. board.html's own lanesHTML(), taskTab(), timeTab(), critTab() and
    timeband(), run in node over a fixture of two services (one live task, one done over its
    estimate, one to do) and again over a plan with no estimate: nothing may draw one, and
    nothing may throw."""
    if not shutil.which("node"):
        print("SKIP S74 - no node on PATH; the board was not drawn")
        return
    src = open(os.path.join(REPO, "ui", "board.html"), encoding="utf-8").read()
    block = re.search(r"(const esc=.*?)\nfunction gutter", src, re.S)
    assert block, "board.html no longer has esc ... critTab ahead of gutter()"
    import datetime
    now = datetime.datetime.now(datetime.timezone.utc)
    iso = lambda m: (now - datetime.timedelta(minutes=m)).isoformat()
    eta = {"phases": {"plan": 5, "implement": 60, "test": 10}, "totalMin": 75, "leftMin": 60,
           "likelyMin": 80}
    tasks = [
        {"id": "T1", "title": "Schema", "service": "api", "status": "done", "owner": "coder",
         "startedAt": iso(40), "doneAt": iso(25), "minutes": 10, "size": "M", "complexity": "low",
         "criteriaRef": ["AC1"]},
        {"id": "T2", "title": "Endpoint", "service": "web", "status": "in_progress", "owner": "coder",
         "startedAt": iso(12), "minutes": 65, "size": "L", "complexity": "high",
         "reason": "touches the session store", "criteriaRef": ["AC2"]},
        {"id": "T3", "title": "Screen", "service": "web", "status": "todo", "owner": "coder",
         "minutes": 20, "size": "M", "complexity": "medium", "reason": "two states",
         "criteriaRef": ["AC2"]},
    ]
    run = {"slug": "x", "status": "running", "phase": "implement", "activeAgent": "coder",
           "eta": eta, "clock": {"at": iso(1), "work": {"plan": 5, "implement": 20}, "waitMin": 0,
                                 "pausedMin": 0}}
    bare = [{k: v for k, v in t.items() if k not in ("minutes", "size", "complexity", "reason")}
            for t in tasks]
    plan = {"acceptanceCriteria": ["AC1 - Schema exists", "AC2 - Endpoint answers"]}
    js = ("const el={hidden:false,innerHTML:''};var document={getElementById:()=>el};"
          "var location={pathname:'/r/x',search:''};\n" + block.group(1) +
          "\nconst fx=" + json.dumps({"run": run, "tasks": tasks, "bare": bare, "plan": plan}) + ";\n"
          "const o={};\n"
          "S={run:fx.run,plan:fx.plan,tasks:fx.tasks,messages:[]};SEL='T2';\n"
          "o.cols=lanesHTML().cols;o.lanes=lanesHTML().h;o.live=taskTab();o.time=timeTab();o.crit=critTab();"
          "timeband();o.band=el.innerHTML;SEL='T1';o.done=taskTab();\n"
          "S={run:{slug:'x',status:'running',phase:'implement'},plan:fx.plan,tasks:fx.bare,messages:[]};"
          "SEL='T2';o.bareLanes=lanesHTML().h;o.bareTask=taskTab();o.bareTime=timeTab();"
          "timeband();o.bareHidden=el.hidden;\n"
          "console.log(JSON.stringify(o));")
    r = subprocess.run(["node", "-e", js], capture_output=True, text=True, encoding="utf-8",
                       timeout=60)
    assert r.returncode == 0, f"board.html did not draw:\n{r.stdout}{r.stderr}"
    o = json.loads(r.stdout)
    assert "10m left" not in o["lanes"], "a finished task still counts as work left"
    for want in ("api", "web", "1h 13m left", "12 of 1h 05m", "20m"):
        assert want in o["lanes"], f"the lanes lack {want!r}"
    assert "reached review" not in o["lanes"], "the lane head counts tasks, not time"
    assert o["cols"].endswith("repeat(6,minmax(112px,1fr))"), f"the six stages are not equal widths: {o['cols']}"
    for want in ("L</span> baseline 25m", "high", "touches the session store", "Estimate", "Actual",
                 "AC2", "coder on it now"):
        assert want in o["live"], f"the Task tab lacks {want!r}"
    assert "5m over its estimate" in o["done"], "a task over its estimate does not say by how much"
    for n in ("plan", "implement", "test", "waiting", "paused"):
        assert f"<span>{n}</span>" in o["time"], f"the Time tab has no {n!r} row"
    for want in ("AC1", "AC2", "0 of 2 met"):
        assert want in o["crit"], f"the Criteria tab lacks {want!r}"
    for want in ("Work completed at", "Work left", "Worked so far", "Waited on you", "slack"):
        assert want in o["band"], f"the time band lacks {want!r}"
    assert " left" not in o["bareLanes"] and "reached" not in o["bareLanes"],         "a plan with no estimate drew a time left (AC12)"
    assert "before tasks carried an estimate" in o["bareTask"], "the Task tab has no hint (AC12)"
    assert "No estimate for this run" in o["bareTime"], "the Time tab has no hint (AC12)"
    assert o["bareHidden"] is True, "the time band showed with no estimate (AC12)"


def the_hall_lays_cards_three_to_a_row():
    """S75 - AC9. A wide screen holds three cards to a row, narrowing to two then one."""
    with open(HALL_HTML, encoding="utf-8") as f:
        src = f.read()
    assert re.search(r"#hall\{[^}]*grid-template-columns:repeat\(3,", src), "the hall is not three to a row"
    assert re.search(r"max-width:1340px\)\s*\{\s*#hall\{grid-template-columns:repeat\(2,", src), "no two-up step"
    assert re.search(r"max-width:1010px\)\s*\{\s*#hall\{grid-template-columns:minmax\(0,1fr\)", src), "no one-up step"


def the_floor_widens_to_fit_the_screen():
    """S77 - AC10. Past six teams the office picks the column count that fits the window:
    25 teams on 1500x950 and 1100x700 fit whole, and the generated corridors are all
    axis-aligned and never cross an island. Six teams or fewer keep three columns."""
    if not shutil.which("node"):
        print("SKIP S77 - no node on PATH; the floor was not laid out")
        return
    src = open(HALL_HTML, encoding="utf-8").read()
    geo = src[src.index("const BUILDING_W"):src.index("function podSig")]
    js = geo + """
const out={};
for(const [cw,ch] of [[1500,950],[1100,700]]){
  const N=pickCols(25,26,cw,ch,78,52), d=floorDims(N,26), g=floorGraph(N,d.rows);
  const isl=[]; for(let i=0;i<26;i++) isl.push([18+194*(i%N),16+206*Math.floor(i/N)]);
  out[cw]={N,d,tall:Math.max(...isl.map(a=>a[1]))+170,wide:Math.max(...isl.map(a=>a[0]))+156,nodes:g.nodes,edges:g.edges,isl,z:Math.min((cw-32)/d.w,(ch-130)/d.h)};
}
out.few=pickCols(6,7,1500,950,78,52);
console.log(JSON.stringify(out));"""
    r = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, f"hall.html's floor layout did not run: {r.stdout}{r.stderr}"
    out = json.loads(r.stdout)
    body = src[src.index("function renderOffice"):]
    assert body.count("pickCols(") >= 2, "the floor does not re-pick N once the key exists (first open re-lays itself)"
    assert re.search(r'"c":\[193,206\],"d":\[387,206\]', src), "the three-column corridor is off y 206"
    assert out["few"] == 3, "six teams or fewer must keep the three-column floor"
    for key in ("1500", "1100"):
        o = out[key]
        assert o["N"] > 3 and o["z"] >= 0.5, f"25 teams at {key}px do not fit: {o['N']} cols, zoom {o['z']}"
        n = o["nodes"]
        assert o["wide"] <= o["d"]["w"] and o["tall"] <= o["d"]["h"], f"an island hangs off the {key}px floor"
        assert any(y == 206 for _, y in n.values()), "no between-rows corridor at y 206"
        for a, b in o["edges"]:
            (ax, ay), (bx, by) = n[a], n[b]
            assert (ax == bx) != (ay == by), f"edge {a}-{b} is diagonal"
            for x, y in o["isl"]:       # the island box, its rug and tag excluded
                if ax == bx:
                    hit = x <= ax <= x + 156 and min(ay, by) < y + 118 and max(ay, by) > y
                else:
                    hit = y <= ay <= y + 118 and min(ax, bx) < x + 156 and max(ax, bx) > x
                assert not hit, f"edge {a}-{b} crosses the island at ({x},{y})"


SCENARIOS = [
    ("S1", merge_lands_on_each_repos_own_base),
    ("S2/S5/S6/S8/S9/S10", workstream_checks),
    ("S3", wave_two_reattaches_to_the_one_branch),
    ("S4", init_refuses_a_non_slug_identity),
    ("S7", teardown_removes_every_container),
    ("S11", apply_refuses_a_repo_off_its_base),
    ("S12", apply_refuses_a_dirty_working_tree),
    ("S13", finish_reports_a_missing_repo_loudly),
    ("S14/S16/S17/S20/S21", core_checks),
    ("S15", slug_rule_edges),
    ("S18", review_rejections_never_touch_disk),
    ("S19", reviewer_holds_no_write_tool),
    ("S22", qa_check_spans_service_namespaces),
    ("S23", command_drift_check),
    ("S24", drift_guard_catches_an_unknown_command),
    ("S25", init_stdout_is_machine_readable),
    ("S26", archive_never_moves_what_the_bus_does_not_own),
    ("S27", qa_check_fails_when_a_review_is_missing),
    ("S28", real_service_names_survive_byte_for_byte),
    ("S29", a_service_name_cannot_escape_its_container),
    ("S30", an_explicit_empty_service_is_not_the_flat_layout),
    ("S31", a_mid_loop_merge_failure_names_the_half_shipped_repos),
    ("S32", ls_reports_branch_drift_and_orphan_containers),
    ("S33", prune_lists_before_it_removes),
    ("S34", the_gate_round_trips_beside_the_bus),
    ("S35", a_previous_runs_gate_does_not_release_this_one),
    ("S36", the_gate_endpoint_is_the_security_boundary),
    ("S37", both_gate_writers_agree_on_the_format),
    ("S38", the_listen_call_is_explicit_about_loopback),
    ("S39", the_hall_carries_its_palette_and_needs_no_network),
    ("S49", the_board_matches_the_hall_and_needs_no_network),
    ("S58", a_coded_task_is_not_done_until_its_service_is),
    ("S59", prune_gives_back_a_done_workstreams_worktrees_once_its_work_has_landed),
    ("S60", a_hide_lasts_for_the_run_it_was_made_in),
    ("S61", the_runbook_fits_what_survives_a_compaction),
    ("S62", a_plan_gate_card_carries_the_plan),
    ("S63", ship_waits_for_a_fresh_chat_once),
    ("S64", a_usage_limit_reads_as_a_pause),
    ("S65", the_next_coder_takes_at_most_two_ready_tasks),
    ("S66", every_role_runs_on_a_chosen_model),
    ("S69", a_run_carries_its_own_estimate_and_closes_itself),
    ("S70", the_estimate_clock_and_close_hold_at_their_edges),
    ("S71", a_project_names_its_own_human_steps),
    ("S72", the_final_button_and_the_payload_are_tested),
    ("S72b", the_write_endpoints_refuse_cross_site_posts),
    ("S73", the_workstream_card_shows_the_estimate),
    ("S74", the_board_draws_the_lanes_the_inspector_and_the_time_band),
    ("S75", the_hall_lays_cards_three_to_a_row),
    ("S76", a_write_survives_a_reader_holding_the_file),
    ("S77", the_floor_widens_to_fit_the_screen),
    ("S67", the_design_rules_and_their_fixes_stay_in_sync),
    ("S68", scenarios_are_written_as_use_cases),
    ("S53", every_agent_names_a_skill_that_exists),
    ("S54", no_tracked_source_carries_a_byte_order_mark),
    ("S55", a_plan_the_pipeline_cannot_use_is_refused),
    ("S56", test_results_are_written_through_a_check),
    ("S57", the_fix_budget_is_counted_where_it_is_kept),
    ("S50", the_hall_boots_from_the_bus_not_the_fixture),
    ("S51", slug_derivation_strips_decoration_at_either_end),
    ("S52", a_later_wave_lands_on_the_same_branch),
    ("S47", heartbeat_keeps_a_long_command_from_looking_dead),
    ("S48", an_inherited_failure_needs_evidence_not_a_smaller_number),
    ("S40", the_root_route_serves_the_hall),
    ("S41", every_character_has_both_hair_layers),
    ("S42", the_motion_inventory_stays_at_eight),
    ("S43", the_corridor_graph_never_cuts_a_corner),
    ("S44", the_operator_is_gated_and_reports_evidence),
    ("S45", the_planner_is_granted_the_graph_it_is_told_to_query),
    ("S46", every_agent_carries_a_bounded_cheatsheet),
]


def main():
    failed = []
    for sid, fn in SCENARIOS:
        try:
            fn()
        except Exception as e:          # one broken scenario must not hide the rest
            failed.append((sid, fn.__name__, f"{type(e).__name__}: {e}"))
            print(f"FAIL {sid} {fn.__name__}\n  {e}\n")
    if failed:
        print(f"{len(SCENARIOS) - len(failed)}/{len(SCENARIOS)} scenario groups passed; "
              f"failed: {', '.join(s for s, _, _ in failed)}")
        sys.exit(1)
    print("ok - pipe.py self-check passed")


if __name__ == "__main__":
    main()
