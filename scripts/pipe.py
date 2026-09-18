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
    pipe.py worktree add --service api --repo /abs/repos/OpenCRM
    pipe.py task add --id T1 --title "Add /logout controller" --owner coder
    pipe.py task update --id T1 --status done
    pipe.py status
"""
import argparse, json, os, re, subprocess, sys, tempfile, time
from datetime import datetime, timezone

PHASES = ["spec", "plan", "implement", "test", "review", "qa", "done"]
RUN_STATUSES = ["running", "awaiting_approval", "blocked", "done", "failed"]
CONFIG_NAME = "agent-orchestration.config.json"
# A spec doc named one of these says nothing about the workstream — its parent dir does.
GENERIC_SPEC_NAMES = {"design", "spec", "readme", "index", "requirements", "plan"}
SLUG_MAX = 40


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
    print(json.dumps(run, indent=2))
    # Last line is the resolved bus: --slug moves it off ./pipeline, and the entry skill
    # is the only thing that knows where it went. It bakes this into $PIPE --root.
    print(root)


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
    s = sub.add_parser("worktree")
    ws = s.add_subparsers(dest="wt_cmd", required=True)
    w = ws.add_parser("add"); w.add_argument("--service", required=True); w.add_argument("--repo", required=True)
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
        "worktree": cmd_worktree,
    }[args.cmd](root, args)


if __name__ == "__main__":
    main()
