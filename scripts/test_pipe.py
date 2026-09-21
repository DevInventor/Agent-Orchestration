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
               if os.path.isfile(p)])
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


def reviewer_holds_no_write_tool():
    """S19 - AC7 names the tool grant explicitly; it is the permission boundary."""
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    text = open(os.path.join(repo, "agents", "reviewer.md"), encoding="utf-8").read()
    tools = [l for l in text.splitlines() if l.startswith("tools:")]
    assert len(tools) == 1, tools
    granted = {t.strip() for t in tools[0].split(":", 1)[1].split(",")}
    assert "Bash" in granted, f"the reviewer needs Bash to call pipe.py: {granted}"
    assert not granted & {"Write", "Edit"}, f"the reviewer must hold no Write/Edit: {granted}"
    assert re.search(r"(pipe\.py|\$PIPE)\s+review\s+--from", text), \
        "reviewer.md must tell the reviewer how it persists findings"


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
