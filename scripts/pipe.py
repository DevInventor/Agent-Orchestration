#!/usr/bin/env python3
"""
pipe.py - the shared coordination bus for the Agent-Orchestration multi-agent pipeline.

Every agent coordinates through files under <repo>/pipeline. This CLI is the
ONLY sanctioned way to touch that state, so writes stay atomic and the append
-only message log never corrupts under concurrent subagents.

Phases (drive the header progress bar), in order:
    spec -> plan -> implement -> test -> review -> qa -> done

Usage examples:
    pipe.py init --feature "Add SSO logout endpoint"
    pipe.py slug --spec docs/specs/009-messaging-hub/design.md
    pipe.py phase plan
    pipe.py agent planner
    pipe.py progress 30
    pipe.py loop --count 2 --max 5
    pipe.py event --agent coder --type handoff --summary "Implemented 4/4 tasks" --ref pipeline/code/changes.json
    pipe.py review --from /tmp/findings.json
    pipe.py qa-check
    pipe.py worktree add --service api --repo /abs/repos/OpenCRM
    pipe.py finish 009-messaging-hub --apply
    pipe.py task add --id T1 --title "Add /logout controller" --owner coder
    pipe.py task update --id T1 --status done
    pipe.py status
"""
import argparse, json, os, re, shutil, subprocess, sys, tempfile, time
from datetime import datetime, timezone

PHASES = ["spec", "plan", "implement", "test", "review", "qa", "done"]
RUN_STATUSES = ["running", "awaiting_approval", "blocked", "done", "failed"]
CONFIG_NAME = "agent-orchestration.config.json"
# A spec doc named one of these says nothing about the workstream — its parent dir does.
GENERIC_SPEC_NAMES = {"design", "spec", "readme", "index", "requirements", "plan"}
SLUG_MAX = 40
SEVERITIES = ["blocking", "major", "minor", "nit"]
RECOMMENDATIONS = ["approve", "approve-with-notes", "changes-required"]


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def find_pipeline(start="."):
    """Walk up from cwd to locate an existing pipeline/ dir; default to ./pipeline."""
    cur = os.path.abspath(start)
    while True:
        cand = os.path.join(cur, "pipeline")
        if os.path.isdir(cand):
            return cand
        parent = os.path.dirname(cur)
        if parent == cur:
            return os.path.abspath(os.path.join(start, "pipeline"))
        cur = parent


def find_config(start="."):
    """Walk up from cwd to locate agent-orchestration.config.json. Returns path or None."""
    cur = os.path.abspath(start)
    while True:
        cand = os.path.join(cur, CONFIG_NAME)
        if os.path.isfile(cand):
            return cand
        parent = os.path.dirname(cur)
        if parent == cur:
            return None
        cur = parent


def pipelines_root():
    """The one place every workstream's bus lives. Separate repos have no shared root
    to put state in, so it is fixed and absolute. $AGENT_ORCHESTRATION_HOME overrides
    the ~/.agent-orchestration part (tests, and anyone keeping state off the home drive)."""
    home = os.environ.get("AGENT_ORCHESTRATION_HOME") or \
        os.path.join(os.path.expanduser("~"), ".agent-orchestration")
    return os.path.join(home, "pipelines")


def scan_pipelines():
    """Every bus under the fixed root: [{slug, root, run}]. The directory IS the
    registry — nothing to register, nothing to keep in sync, self-healing when one is
    deleted. `slug` collision-checks against it and `finish` resolves a slug through it."""
    base, out = pipelines_root(), []
    for name in sorted(os.listdir(base)) if os.path.isdir(base) else []:
        rp = os.path.join(base, name, "pipeline", "run.json")
        if os.path.isfile(rp):
            out.append({"slug": name, "root": os.path.dirname(rp), "run": read_json(rp, {})})
    return out


def git(repo, *args, check=True):
    """Every git call goes through here. encoding is pinned: git prints paths in the
    console codepage on Windows, and decoding them with the locale default mangles any
    non-ASCII filename in a conflict report - exactly where accuracy matters most."""
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        sys.exit(f"git {' '.join(args)} failed in {repo}:\n{(r.stderr or r.stdout).strip()}")
    return r


def slugify(text):
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:SLUG_MAX].strip("-")


def derive_slug(spec_path):
    """The workstream's name, from its spec doc's path. It has to be *derived* rather
    than chosen, because a later wave re-derives it and must land on the same string —
    that is what keeps one workstream on one branch. A plain basename yields 'design'
    for 3 of 7 real spec paths and a plain parent yields 'specs'/'docs' for 4, so the
    rule uses the basename unless it is generic, then strips date/kind decoration."""
    p = spec_path.replace("\\", "/").rstrip("/")
    stem = os.path.splitext(os.path.basename(p))[0]
    if stem.lower() in GENERIC_SPEC_NAMES:
        stem = os.path.basename(os.path.dirname(p))
    stem = re.sub(r"^\d{4}-\d{2}-\d{2}-", "", stem)
    stem = re.sub(r"-(design|spec)$", "", stem, flags=re.IGNORECASE)
    return slugify(stem)


def resolve_slug(slug):
    """Suffix rather than reuse an ACTIVE workstream's slug — two live runs sharing a
    slug would share a branch, a container and a bus directory. A closed one is free."""
    active = {p["slug"] for p in scan_pipelines()
              if p["run"].get("status") not in ("done", "failed")}
    if slug not in active:
        return slug
    n = 2
    while f"{slug}-{n}" in active:
        n += 1
    return f"{slug}-{n}"


def atomic_write(path, text):
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


class Lock:
    """Portable advisory lock (WSL2 + native Windows) via O_CREAT|O_EXCL lockfile.
    Wrap read-modify-write of run.json / tasks.json so parallel service teams
    don't lose updates. NOT used for messages.jsonl — single-line appends <4KB
    are atomic, and locking the log would serialize events and kill parallelism.
    ponytail: spin-wait with stale-steal; fine for a handful of concurrent
    subagents. Swap for fcntl/msvcrt if contention ever gets heavy."""
    def __init__(self, path, timeout=10, stale=30):
        self.lp, self.timeout, self.stale, self.fd = path + ".lock", timeout, stale, None

    def __enter__(self):
        start = time.time()
        while True:
            try:
                self.fd = os.open(self.lp, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                return self
            except FileExistsError:
                try:
                    if time.time() - os.path.getmtime(self.lp) > self.stale:
                        os.unlink(self.lp); continue
                except FileNotFoundError:
                    continue
                if time.time() - start > self.timeout:
                    raise TimeoutError(f"lock busy: {self.lp}")
                time.sleep(0.05)

    def __exit__(self, *a):
        try: os.close(self.fd)
        except Exception: pass
        try: os.unlink(self.lp)
        except FileNotFoundError: pass


def read_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def run_path(root):
    return os.path.join(root, "run.json")


def load_run(root):
    return read_json(run_path(root), {})


def save_run(root, run):
    run["updatedAt"] = now_iso()
    atomic_write(run_path(root), json.dumps(run, indent=2))


def recompute_progress(run):
    """Progress = phase completion + partial credit for the coder/test loop."""
    phase = run.get("phase", "spec")
    idx = PHASES.index(phase) if phase in PHASES else 0
    base = idx / (len(PHASES) - 1)
    run["progressPct"] = round(base * 100)


def cmd_slug(root, args):
    """Print the workstream slug for a spec doc (or a bare feature title), collision
    -checked against the active workstreams. The entry skills call this instead of
    applying the rule by eye, so `init`, a later wave and `finish` all agree."""
    print(resolve_slug(derive_slug(args.spec) if args.spec else slugify(args.title)))


def cmd_init(root, args):
    # The branch name is fixed here and nothing later can change it, so an identity git
    # cannot turn into a ref has to be refused now, not discovered at `worktree add`.
    # Refuse rather than slugify: main() built the bus directory from the raw argument
    # and scan_pipelines() keys on that directory name, so a silent rewrite would leave
    # run["slug"] and the directory disagreeing.
    if getattr(args, "slug", None) and slugify(args.slug) != args.slug:
        sys.exit(f"--slug must already be a slug; {args.slug!r} would have to be "
                 f"{slugify(args.slug)!r}. Run `pipe.py slug --title/--spec ...` and pass its output.")
    os.makedirs(root, exist_ok=True)
    for sub in ("code", "test", "review", "status"):
        os.makedirs(os.path.join(root, sub), exist_ok=True)
    run = {
        # runId now scopes events in the append-only log, so it must be unique.
        # Seconds alone collide when two runs start in the same second.
        "runId": time.strftime("run-%Y%m%d-%H%M%S") + "-" + os.urandom(2).hex(),
        "feature": args.feature,
        "phases": PHASES,
        "phase": "spec",
        "activeAgent": "orchestrator",
        "status": "running",
        "loop": {"count": 0, "max": args.max_loop},
        "progressPct": 0,
        "startedAt": now_iso(),
    }
    if getattr(args, "slug", None):
        # The one moment the branch name comes into existence. Every later step reads
        # it; none may choose one. Waves of the same workstream re-init onto the same
        # slug and so onto the same branch. Omit --slug and this is a legacy bus.
        run["slug"] = args.slug
        run["branch"] = "feature/" + args.slug
        run["repos"] = []
        run["mode"] = "worktree"
    save_run(root, run)
    atomic_write(os.path.join(root, "spec.md"),
                 f"# Feature spec\n\n{args.feature}\n\n_Initialized {now_iso()}_\n")
    atomic_write(os.path.join(root, "tasks.json"), json.dumps({"tasks": []}, indent=2))
    # touch the append-only log
    open(os.path.join(root, "messages.jsonl"), "a", encoding="utf-8").close()
    _event(root, "orchestrator", "status", "spec", f"Run started for: {args.feature}",
           None, None, run_id=run["runId"])
    # stdout is ONE JSON document - callers json.loads() it to read runId/branch, so a
    # trailing bare path line would break them. busPath carries the resolved bus instead:
    # --slug moves it off ./pipeline and the entry skill is the only thing that knows
    # where it went, so it reads this key and bakes it into $PIPE --root. It is printed
    # rather than saved, leaving a no-slug run.json byte-for-byte the legacy one.
    print(json.dumps({**run, "busPath": root}, indent=2))


def _event(root, agent, etype, phase, summary, detail, ref, service=None, run_id=None):
    # runId scopes the event to one run. messages.jsonl is append-only and never
    # rotated, so a long-lived bus accumulates many runs in one file; without this
    # the dashboard cannot tell this run's events from the previous feature's.
    rec = {
        "ts": now_iso(),
        "runId": run_id,
        "agent": agent,
        "type": etype,
        "phase": phase,
        "summary": summary,
    }
    if run_id is None:
        del rec["runId"]
    if service:
        rec["service"] = service
    if detail:
        rec["detail"] = detail
    if ref:
        rec["ref"] = ref
    with open(os.path.join(root, "messages.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
    return rec


def cmd_event(root, args):
    run = load_run(root)
    phase = args.phase or run.get("phase", "spec")
    rec = _event(root, args.agent, args.type, phase, args.summary, args.detail, args.ref,
                 args.service, run.get("runId"))
    print(json.dumps(rec))


def cmd_phase(root, args):
    if args.name not in PHASES:
        sys.exit(f"unknown phase '{args.name}'. valid: {', '.join(PHASES)}")
    with Lock(run_path(root)):
        run = load_run(root)
        run["phase"] = args.name
        recompute_progress(run)
        if args.name == "done":
            run["status"] = "done"
            run["activeAgent"] = "orchestrator"
        save_run(root, run)
    print(f"phase -> {args.name} ({run['progressPct']}%)")


def cmd_agent(root, args):
    with Lock(run_path(root)):
        run = load_run(root)
        run["activeAgent"] = args.name
        save_run(root, run)
    print(f"activeAgent -> {args.name}")


def cmd_progress(root, args):
    with Lock(run_path(root)):
        run = load_run(root)
        run["progressPct"] = max(0, min(100, args.pct))
        save_run(root, run)
    print(f"progress -> {run['progressPct']}%")


def cmd_loop(root, args):
    with Lock(run_path(root)):
        run = load_run(root)
        loop = run.get("loop", {"count": 0, "max": 5})
        if args.count is not None:
            loop["count"] = args.count
        if args.max is not None:
            loop["max"] = args.max
        run["loop"] = loop
        save_run(root, run)
    print(f"loop -> {loop['count']}/{loop['max']}")


def cmd_status_set(root, args):
    """Set the run-level status (e.g. awaiting_approval, running, blocked)."""
    if args.value not in RUN_STATUSES:
        sys.exit(f"unknown status '{args.value}'. valid: {', '.join(RUN_STATUSES)}")
    with Lock(run_path(root)):
        run = load_run(root)
        run["status"] = args.value
        save_run(root, run)
    print(f"status -> {args.value}")


def cmd_svc(root, args):
    """Upsert per-service state into run.services[name] for the dashboard."""
    with Lock(run_path(root)):
        run = load_run(root)
        services = run.setdefault("services", {})
        svc = services.setdefault(args.name, {})
        if args.phase is not None:
            svc["phase"] = args.phase
        if args.agent is not None:
            svc["activeAgent"] = args.agent
        if args.status is not None:
            svc["status"] = args.status
        if args.loop_count is not None or args.loop_max is not None:
            loop = svc.setdefault("loop", {"count": 0, "max": 5})
            if args.loop_count is not None:
                loop["count"] = args.loop_count
            if args.loop_max is not None:
                loop["max"] = args.loop_max
        if args.passed is not None:
            svc["passed"] = args.passed
        if args.failed is not None:
            svc["failed"] = args.failed
        svc["updatedAt"] = now_iso()
        save_run(root, run)
    print(json.dumps({args.name: svc}))


def cmd_status(root, args):
    print(json.dumps(load_run(root), indent=2))


def cmd_config(root, args):
    """Load + validate the optional agent-orchestration.config.json service registry.

    Prints {"configured": false, "services": []} (exit 0) when no config exists —
    absence is valid; the pipeline then falls back to indexing. On a present-but-broken
    config it exits non-zero with a clear message (trust-boundary validation)."""
    path = args.file or find_config()
    if not path or not os.path.isfile(path):
        print(json.dumps({"configured": False, "services": []}))
        return
    try:
        cfg = json.loads(open(path, encoding="utf-8").read())
    except json.JSONDecodeError as e:
        sys.exit(f"config: invalid JSON in {path}: {e}")
    base = os.path.dirname(os.path.abspath(path))
    repos_root = os.path.abspath(os.path.join(base, cfg.get("reposRoot", ".")))
    services = cfg.get("services")
    if not isinstance(services, list) or not services:
        sys.exit(f"config {path}: 'services' must be a non-empty list")
    names, norm = set(), []
    for i, s in enumerate(services):
        name = s.get("name")
        if not name:
            sys.exit(f"config: service #{i} is missing 'name'")
        if name in names:
            sys.exit(f"config: duplicate service name '{name}'")
        names.add(name)
        p = s.get("path", name)
        abspath = p if os.path.isabs(p) else os.path.join(repos_root, p)
        abspath = os.path.abspath(abspath)
        if not os.path.isdir(abspath):
            sys.exit(f"config: service '{name}' path does not exist: {abspath}")
        deps = s.get("dependsOnServices", [])
        if not isinstance(deps, list):
            sys.exit(f"config: service '{name}' dependsOnServices must be a list")
        norm.append({"name": name, "path": abspath, "test": s.get("test"),
                     "build": s.get("build"), "dependsOnServices": deps})
    for s in norm:
        for d in s["dependsOnServices"]:
            if d not in names:
                sys.exit(f"config: service '{s['name']}' dependsOnServices references unknown '{d}'")
    print(json.dumps({"configured": True, "reposRoot": repos_root, "services": norm}, indent=2))


def cmd_task(root, args):
    tp = os.path.join(root, "tasks.json")
    with Lock(tp):
        data = read_json(tp, {"tasks": []})
        tasks = data["tasks"]
        if args.task_cmd == "add":
            task = {
                "id": args.id, "title": args.title,
                "owner": args.owner or "coder", "status": args.status or "todo",
                "createdAt": now_iso(),
            }
            if args.service:
                task["service"] = args.service
            tasks.append(task)
        elif args.task_cmd == "update":
            found = False
            for t in tasks:
                if t["id"] == args.id:
                    if args.title: t["title"] = args.title
                    if args.owner: t["owner"] = args.owner
                    if args.status: t["status"] = args.status
                    if args.service: t["service"] = args.service
                    t["updatedAt"] = now_iso()
                    found = True
            if not found:
                sys.exit(f"no task with id {args.id}")
        atomic_write(tp, json.dumps(data, indent=2))
    print(json.dumps(data, indent=2))


def svc_dir(root, service, *parts):
    """Artifact dir for a service, or the flat single-service layout when there is none."""
    return os.path.join(root, "services", service, *parts) if service \
        else os.path.join(root, *parts)


def render_review(data):
    """review.md is rendered FROM review.json, so the prose and the machine-readable
    findings can never disagree about how many blockers there are."""
    out = ["# Review", "", "## Summary", "",
           str(data.get("summary") or "").strip() or "_not given_",
           "", "## Plan fidelity", "",
           str(data.get("planFidelity") or "").strip() or "_not given_",
           "", "## Findings", ""]
    for sev in SEVERITIES:
        group = [f for f in data["findings"] if f["severity"] == sev]
        if not group:
            continue
        out += [f"### {sev} ({len(group)})", ""]
        for f in group:
            loc = str(f.get("file") or "")
            if f.get("line"):
                loc += f":{f['line']}"
            ref = f" [{f['planRef']}]" if f.get("planRef") else ""
            out.append(f"- **{loc or 'general'}**{ref} - {str(f['note']).strip()}")
        out.append("")
    if not data["findings"]:
        out += ["_no findings_", ""]
    return "\n".join(out + ["## Recommendation", "", data["recommendation"], ""])


def cmd_review(root, args):
    """Persist the reviewer's own findings: validate the whole payload, then write.

    The reviewer calls this instead of returning its analysis for the orchestrator to
    retype - an LLM copy step inside the audit trail can silently drop a finding, merge
    two, or soften a severity, and `qa-check` is only trustworthy because these landed
    schema-checked. Nothing is opened for writing until every finding has passed, so a
    malformed payload is rejected rather than half-written."""
    try:
        with open(args.source, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        sys.exit(f"review: no such file: {args.source}")
    except json.JSONDecodeError as e:
        sys.exit(f"review: invalid JSON in {args.source}: {e}")
    if not isinstance(data, dict):
        sys.exit("review: expected a JSON object {recommendation, findings:[...]}")
    if data.get("recommendation") not in RECOMMENDATIONS:
        sys.exit(f"review: recommendation must be one of {', '.join(RECOMMENDATIONS)}, "
                 f"got {data.get('recommendation')!r}")
    findings = data.get("findings", [])
    if not isinstance(findings, list):
        sys.exit("review: 'findings' must be a list")
    for i, f in enumerate(findings):
        if not isinstance(f, dict):
            sys.exit(f"review: finding #{i} must be an object")
        if f.get("severity") not in SEVERITIES:
            sys.exit(f"review: finding #{i} severity must be one of "
                     f"{', '.join(SEVERITIES)}, got {f.get('severity')!r}")
        if not str(f.get("note", "")).strip():
            sys.exit(f"review: finding #{i} has an empty note - a finding nobody can act on")
    data["findings"] = findings
    out = svc_dir(root, args.service, "review")
    atomic_write(os.path.join(out, "review.json"), json.dumps(data, indent=2))
    atomic_write(os.path.join(out, "review.md"), render_review(data))
    blocking = len([f for f in findings if f["severity"] == "blocking"])
    summary = (f"Review: {blocking} blocking, {len(findings) - blocking} notes "
               f"({data['recommendation']})")
    run = load_run(root)
    _event(root, "reviewer", "finding", run.get("phase", "review"), summary, None,
           os.path.join(out, "review.md"), args.service, run.get("runId"))
    print(summary)


def cmd_qa_check(root, args):
    """The QA gate as an exit code rather than three files and a judgement call.

    A finding counts as unresolved iff it is `blocking` in the CURRENT review.json:
    a re-review overwrites that file, so a fixed finding simply disappears. No finding
    ids, no resolution lifecycle, no second piece of state to keep in agreement."""
    run = load_run(root)
    services = [args.service] if args.service else (sorted(run.get("services", {})) or [None])
    fails = []
    for svc in services:
        where = f"services/{svc}/" if svc else ""
        # None, not {}: `review --from` writes nothing when the payload is malformed,
        # so a MISSING review is the exact failure this gate exists to catch - it must
        # not read as a clean one. Same treatment as results.json below.
        review = read_json(svc_dir(root, svc, "review", "review.json"), None)
        if review is None:
            fails.append(f"no review at {where}review/review.json - the reviewer never reported")
        else:
            blocking = [f for f in review.get("findings", []) if f.get("severity") == "blocking"]
            if blocking:
                fails.append(f"{len(blocking)} blocking finding(s) in {where}review/review.json: "
                             + "; ".join(str(f.get("note", ""))[:60] for f in blocking))
        results = read_json(svc_dir(root, svc, "test", "results.json"), None)
        if results is None:
            fails.append(f"no test results at {where}test/results.json - the tester never reported")
        elif results.get("failed"):
            fails.append(f"{results['failed']} failing test(s) in {where}test/results.json")
    tasks = read_json(os.path.join(root, "tasks.json"), {}).get("tasks", [])
    todo = [t for t in tasks if t.get("status") != "done"]
    if todo:
        fails.append("task(s) not done: "
                     + ", ".join(f"{t['id']} ({t.get('status')})" for t in todo))
    for f in fails:
        print("FAIL " + f)
    if fails:
        sys.exit(1)
    print(f"qa-check: green - {len(tasks)} task(s) done, tests green, no blocking findings")


def cmd_worktree(root, args):
    """Materialise one service's checkout of the workstream branch, and record it.

    There is deliberately no --branch: the name comes from run['branch'] and nowhere
    else. That is what makes "one workstream, one branch name in every repository"
    structural rather than a convention two sessions can drift from (observed in 2 of
    11 real containers, where a merge silently left the fourth repo behind)."""
    run = load_run(root)
    branch = run.get("branch")
    if not branch:
        sys.exit("this bus has no workstream branch - it was created without --slug")
    repo = os.path.abspath(args.repo)
    if not os.path.isdir(repo) or git(repo, "rev-parse", "--git-dir", check=False).returncode != 0:
        sys.exit(f"not a git repository: {repo}")
    repos_root = os.path.dirname(repo)
    # The container is repos-root-shaped and sits OUTSIDE every repo, so nothing in it
    # can be committed into one by accident (section 17).
    if git(repos_root, "rev-parse", "--show-toplevel", check=False).returncode == 0:
        sys.exit(f"refusing: {repos_root} is itself inside a git working tree; the "
                 "container must sit beside the repos, not in one")
    wt = os.path.join(repos_root, "wt-" + run["slug"], args.service)
    base = git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if base == "HEAD":
        sys.exit(f"{repo} is on a detached HEAD - check out the branch this work merges home to")
    if os.path.isdir(wt):
        print(f"worktree already present, reusing: {wt}")   # a later wave re-adding
    else:
        # -b only when the branch is new: a second wave attaches to the branch wave 1
        # created instead of failing or inventing a variant of the name.
        exists = git(repo, "rev-parse", "--verify", "--quiet",
                     "refs/heads/" + branch, check=False).returncode == 0
        git(repo, *(["worktree", "add", wt, branch] if exists
                    else ["worktree", "add", "-b", branch, wt]))
    entry = {"service": args.service, "repo": repo, "worktree": wt,
             "branch": branch, "base": base}
    with Lock(run_path(root)):
        run = load_run(root)
        run["repos"] = [r for r in run.get("repos", [])
                        if r["service"] != args.service] + [entry]
        save_run(root, run)
    print(json.dumps(entry, indent=2))


def require_git(minimum=(2, 38)):
    """`merge-tree --write-tree` - the only way to test a merge without touching a
    working tree - landed in git 2.38. Check once and say so, rather than misparse
    older output and report a clean merge that is not one."""
    r = subprocess.run(["git", "--version"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    m = re.search(r"(\d+)\.(\d+)", r.stdout if r.returncode == 0 else "")
    if not m or (int(m.group(1)), int(m.group(2))) < minimum:
        sys.exit(f"finish needs git >= {minimum[0]}.{minimum[1]}; found "
                 f"'{(r.stdout or r.stderr).strip() or 'no git on PATH'}'")


def merge_conflicts(entry):
    """Conflicting paths for merging the workstream branch into this repo's base, or []
    when the merge is clean. Touches no working tree, so it is safe in plan mode."""
    r = git(entry["repo"], "merge-tree", "--write-tree", "--name-only",
            entry["base"], entry["branch"], check=False)
    if r.returncode == 0:
        return []
    # line 0 is the resulting tree's oid; the conflicted paths follow, then a blank
    # line and git's human-readable messages. Any non-zero exit counts as conflicted.
    files = []
    for line in r.stdout.splitlines()[1:]:
        if not line.strip():
            break
        files.append(line.strip())
    return files or ["(git reported a conflict but named no file)"]


def cmd_finish(root, args):
    """Close a run: plan the multi-repo merge, or perform it all-or-nothing.

    Git has no atomic multi-repo merge, so this builds one: every repo is dry-run
    first and nothing merges unless all of them are clean. Merging until something
    breaks would leave one feature half-shipped across services.

    A run is not a workstream: --apply keeps the worktrees, because a later wave stands
    on them. Removing the container is --teardown, a separate explicit act."""
    if args.teardown and not args.apply:
        sys.exit("--teardown only applies with --apply; a bare finish changes nothing")
    if args.slug:
        match = [p for p in scan_pipelines() if p["slug"] == args.slug]
        if not match:
            sys.exit(f"no workstream '{args.slug}' under {pipelines_root()}")
        root = match[0]["root"]
    run = load_run(root)
    repos = run.get("repos") or []
    if not repos:
        sys.exit(f"{root} records no repositories - nothing to finish. "
                 + ("Run `worktree add` first." if run.get("slug")
                    else "This bus was created without --slug."))
    require_git()
    for e in repos:
        n = git(e["repo"], "rev-list", "--count", f"{e['base']}..{e['branch']}").stdout.strip()
        files = merge_conflicts(e)
        verdict = "clean" if not files else "CONFLICTS: " + ", ".join(files)
        # Zero commits is a red flag, not a no-op: it means nothing was ever committed.
        flag = "  <- NO COMMITS on this branch" if n == "0" else ""
        print(f"{e['service']}: {e['branch']} -> {e['base']}  {n} commit(s)  {verdict}{flag}")
    if not args.apply:
        print(f"plan only - nothing changed. re-run with --apply to merge {len(repos)} repo(s).")
        return
    # Re-run every dry run before touching anything: the plan above may have been
    # printed minutes ago in another invocation and the bases may have moved since.
    blocked = []
    for e in repos:
        files = merge_conflicts(e)
        if files:
            blocked.append(f"{e['service']} ({e['repo']}): " + ", ".join(files))
        if git(e["repo"], "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() != e["base"]:
            blocked.append(f"{e['service']} ({e['repo']}): not on its base branch {e['base']}")
        if git(e["repo"], "status", "--porcelain").stdout.strip():
            blocked.append(f"{e['service']} ({e['repo']}): uncommitted changes in the working tree")
    if blocked:
        print("merged NOTHING - resolve these first:")
        for b in blocked:
            print("  " + b)
        sys.exit(1)
    # Preflight makes a failure here unlikely, not impossible (hooks, signing, a ref
    # that moved since). Git has no multi-repo rollback, so name the half-shipped state
    # and the undo rather than exit on a bare git error the operator has to reconstruct.
    merged = []
    for e in repos:
        r = git(e["repo"], "merge", "--no-ff", "-m",
                f"Merge {e['branch']} into {e['base']}", e["branch"], check=False)
        if r.returncode != 0:
            print(f"merge FAILED in {e['repo']} ({e['service']}):\n"
                  f"{(r.stderr or r.stdout).strip()}")
            print(f"HALF-SHIPPED: {len(merged)} of {len(repos)} repo(s) already merged"
                  + (":" if merged else " - nothing to undo."))
            for m in merged:
                print(f"  {m['service']}: {m['branch']} -> {m['base']} in {m['repo']}")
                print(f"    undo: git -C {m['repo']} reset --hard ORIG_HEAD")
            sys.exit(1)
        merged.append(e)
        print(f"merged {e['branch']} -> {e['base']} in {e['repo']}")
    if args.teardown:
        for e in repos:
            git(e["repo"], "worktree", "remove", "--force", e["worktree"], check=False)
        # Services in separate repos put their containers under different repos roots,
        # so there is one container per root, not one per run. Missing the others leaves
        # exactly the empty orphan directories teardown exists to prevent.
        for container in sorted({os.path.dirname(e["worktree"]) for e in repos}):
            shutil.rmtree(container, ignore_errors=True)
            print(f"removed container {container}")
    print(f"archived bus -> {archive_bus(root, run)}")


def archive_bus(root, run):
    """One archive convention, replacing the four hand-rolled variants seen in real use.
    The workstream directory (bus and all) moves aside as <slug>.closed-<YYYYmmdd>.

    Only under the canonical pipelines_root()/<slug>/pipeline layout does the bus OWN
    its parent directory. Under --root the parent is an arbitrary user directory that
    may hold source beside the bus, so there only the bus itself moves - archiving it
    would otherwise carry a sibling src/ off with it."""
    root = os.path.abspath(root)
    ws = os.path.dirname(root)
    stamp = datetime.now().strftime("%Y%m%d")
    if os.path.normcase(os.path.dirname(ws)) == os.path.normcase(pipelines_root()):
        dest = os.path.join(os.path.dirname(ws), f"{run['slug']}.closed-{stamp}")
    else:
        ws, dest = root, f"{root}.closed-{stamp}"
    n, base = 2, dest
    while os.path.exists(dest):       # a workstream closed twice in one day
        dest, n = f"{base}-{n}", n + 1
    shutil.move(ws, dest)
    return dest


def build_parser():
    p = argparse.ArgumentParser(description="Agent-Orchestration pipeline bus")
    p.add_argument("--root", default=None, help="pipeline dir (default: auto-locate ./pipeline)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init"); s.add_argument("--feature", required=True); s.add_argument("--slug", default=None); s.add_argument("--max-loop", type=int, default=5, dest="max_loop")
    s = sub.add_parser("slug"); g = s.add_mutually_exclusive_group(required=True); g.add_argument("--spec"); g.add_argument("--title")
    s = sub.add_parser("event")
    s.add_argument("--agent", required=True)
    s.add_argument("--type", required=True, choices=["status", "handoff", "finding", "question", "result", "error"])
    s.add_argument("--phase", default=None)
    s.add_argument("--summary", required=True)
    s.add_argument("--detail", default=None)
    s.add_argument("--ref", default=None)
    s.add_argument("--service", default=None)
    s = sub.add_parser("phase"); s.add_argument("name")
    s = sub.add_parser("agent"); s.add_argument("name")
    s = sub.add_parser("progress"); s.add_argument("pct", type=int)
    s = sub.add_parser("loop"); s.add_argument("--count", type=int); s.add_argument("--max", type=int)
    s = sub.add_parser("set-status"); s.add_argument("value", choices=RUN_STATUSES)
    s = sub.add_parser("svc")
    s.add_argument("--name", required=True)
    s.add_argument("--phase", default=None)
    s.add_argument("--agent", default=None)
    s.add_argument("--status", default=None)
    s.add_argument("--loop-count", type=int, default=None, dest="loop_count")
    s.add_argument("--loop-max", type=int, default=None, dest="loop_max")
    s.add_argument("--passed", type=int, default=None)
    s.add_argument("--failed", type=int, default=None)
    s = sub.add_parser("status")
    s = sub.add_parser("config"); s.add_argument("--file", default=None)
    s = sub.add_parser("review"); s.add_argument("--from", required=True, dest="source"); s.add_argument("--service", default=None)
    s = sub.add_parser("qa-check"); s.add_argument("--service", default=None)
    s = sub.add_parser("worktree")
    ws = s.add_subparsers(dest="wt_cmd", required=True)
    w = ws.add_parser("add"); w.add_argument("--service", required=True); w.add_argument("--repo", required=True)
    s = sub.add_parser("finish"); s.add_argument("slug", nargs="?"); s.add_argument("--apply", action="store_true"); s.add_argument("--teardown", action="store_true")
    s = sub.add_parser("task")
    ts = s.add_subparsers(dest="task_cmd", required=True)
    for name in ("add", "update"):
        t = ts.add_parser(name)
        t.add_argument("--id", required=True)
        t.add_argument("--title", default=None)
        t.add_argument("--owner", default=None)
        t.add_argument("--status", default=None, choices=["todo", "in_progress", "done", "blocked"])
        t.add_argument("--service", default=None)
    return p


def main():
    args = build_parser().parse_args()
    # `init` creates ./pipeline in the CURRENT dir — it must never walk up, or a run
    # started in a subdir would hijack/overwrite a parent's existing pipeline (data
    # loss). Every other command walks up to locate the active bus.
    if args.cmd == "init":
        # --slug puts the bus under the fixed pipelines root, where it outlives the cwd
        # it was started from; --root still wins, so an existing ./pipeline run is
        # untouched (backward compatibility, spec sections 7 and 16).
        root = args.root or (os.path.join(pipelines_root(), args.slug, "pipeline")
                             if args.slug else os.path.abspath("pipeline"))
    else:
        root = args.root or find_pipeline()
    {
        "init": cmd_init, "slug": cmd_slug, "event": cmd_event, "phase": cmd_phase,
        "agent": cmd_agent, "progress": cmd_progress, "loop": cmd_loop,
        "set-status": cmd_status_set, "svc": cmd_svc,
        "status": cmd_status, "config": cmd_config, "task": cmd_task,
        "review": cmd_review, "qa-check": cmd_qa_check,
        "worktree": cmd_worktree, "finish": cmd_finish,
    }[args.cmd](root, args)


if __name__ == "__main__":
    main()
