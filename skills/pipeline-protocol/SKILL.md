---
name: pipeline-protocol
description: The shared coordination contract for the Agent-Orchestration pipeline. Consult whenever an agent (planner, coder, tester, reviewer, or the orchestrator) needs to read from or write to the ./pipeline bus, emit a status/handoff event, update the phase or progress bar, or understand the file layout every agent shares. Use this before touching any file under ./pipeline.
---

# Pipeline protocol

All four agents are stateless subagents. They never talk to each other directly —
they coordinate **only** through files under `<repo>/pipeline`. Treat this directory
as a shared message bus. Always mutate it through the `pipe.py` CLI so writes stay
atomic and the message log never corrupts under concurrent agents.

`pipe.py` lives at `${CLAUDE_PLUGIN_ROOT}/scripts/pipe.py`. Run it from the repo root
(it auto-locates `./pipeline`).

## File layout

```
pipeline/
├── run.json          # single source of truth for the dashboard header
├── spec.md           # normalized feature spec (orchestrator writes)
├── index.md          # planner's lightweight codebase index (shared understanding)
├── plan.md           # planner output, human-readable
├── plan.json         # planner output, structured: tasks, files, acceptance criteria
├── tasks.json        # the task board  -> right panel
├── messages.jsonl    # append-only event log  -> left panel (agent comms)
├── code/
│   ├── changes.json  # coder: {summary, files:[...], notes}
│   └── diff.patch    # coder: unified diff of the change (git diff)
├── test/
│   ├── scenarios.json# tester: use-case + dataflow scenarios
│   └── results.json  # tester: {iteration, passed, failed, failures:[...]}
├── review/
│   ├── review.md     # reviewer analysis (orchestrator persists it — see below)
│   └── review.json   # reviewer findings: [{severity, file, line, note, planRef}]
└── status/
    └── summary.md     # QA/orchestrator: completed + current task  -> right panel
```

### Multi-service runs (>1 service): per-service artifact namespace

The flat `code/`, `test/`, `review/` dirs above are the **single-service** layout and
stay exactly as-is for a plain `/ship`. When a run builds more than one service, each
service's coder/tester/reviewer batch writes its artifacts under a per-service namespace
so concurrent same-batch subagents never clobber a shared file:

```
pipeline/services/<service>/
├── code/{changes.json,diff.patch}
├── test/{scenarios.json,results.json}
└── review/{review.md,review.json}
```

`run.json`, `tasks.json`, and `messages.jsonl` stay **shared** (one board, one log):
tasks carry a `service` field, events carry `--service`, and per-service header state
lives in `run.services[<service>]` via `pipe.py svc`. Those shared files are
concurrency-safe because `pipe.py` guards them with a lock; the append-only
`messages.jsonl` is safe without one. Only the free-form artifact files above need the
per-service path.

## run.json (drives the progress bar)

```json
{
  "runId": "run-YYYYmmdd-HHMMSS",
  "feature": "...",
  "phases": ["spec","plan","implement","test","review","qa","done"],
  "phase": "implement",
  "activeAgent": "coder",
  "status": "running|awaiting_approval|blocked|done|failed",
  "loop": { "count": 2, "max": 5 },
  "progressPct": 45,
  "services": {
    "oauth_v3.8.0": { "phase":"test", "activeAgent":"tester",
      "status":"running", "loop":{"count":2,"max":5}, "passed":8, "failed":1 }
  }
}
```

`status: awaiting_approval` is the finalize gate (plan done, waiting for the user).
`services` is present only in a multi-service run — one entry per service, written by
`pipe.py svc`. The header `phase`/`progressPct`/`loop` stay the **macro** run; each
service's granular phase and fix-loop live under its `services` entry.

## messages.jsonl (one JSON object per line)

```json
{ "ts":"ISO-8601", "agent":"planner|coder|tester|reviewer|orchestrator",
  "type":"status|handoff|finding|question|result|error",
  "phase":"plan", "summary":"one human-readable line",
  "service":"oauth_v3.8.0 (optional; multi-service runs)",
  "detail":"optional longer text", "ref":"pipeline/plan.md" }
```

Keep `summary` to one line — it is what a human skims in the dashboard. Put anything
long in `detail` or in a referenced file via `ref`.

## The CLI you will actually call

```bash
PIPE="python3 ${CLAUDE_PLUGIN_ROOT}/scripts/pipe.py"

$PIPE init --feature "..."                 # orchestrator only, once
$PIPE phase plan                           # advance the phase (recomputes progress)
$PIPE agent coder                          # set the active agent
$PIPE progress 60                          # optional manual progress override
$PIPE loop --count 2 --max 5               # coder<->tester loop counter (single-service)
$PIPE set-status awaiting_approval         # run-level status (finalize gate, blocked, running…)
$PIPE task add --id T1 --title "..." --owner coder [--service oauth_v3.8.0]
$PIPE task update --id T1 --status done [--service oauth_v3.8.0]
$PIPE event --agent coder --type handoff --summary "..." [--detail "..."] [--ref path] [--service oauth_v3.8.0]
$PIPE svc --name oauth_v3.8.0 --phase test --loop-count 2 --loop-max 5 \
          --agent tester --status running --passed 8 --failed 1   # per-service header state
$PIPE status                               # print run.json
$PIPE config                               # load+validate optional agent-orchestration.config.json
```

`--service` and `svc` are **optional/additive**: omit them and behavior is identical to
the original single-service pipeline. Use them only in a multi-service run.

## Optional service registry — `agent-orchestration.config.json`

A user may drop a `agent-orchestration.config.json` at their repos root declaring the services
they work with and where those repos live locally. `$PIPE config` walks up to find it,
validates it, and prints normalized JSON:

```json
{ "configured": true, "reposRoot": "/abs/repos",
  "services": [ { "name": "oauth", "path": "/abs/repos/oauth_v3.8.0",
                  "test": "mvn -q test", "build": null, "dependsOnServices": [] } ] }
```

When absent it prints `{"configured": false, "services": []}` (exit 0) and the pipeline
falls back to discovering service dirs by indexing — so the registry is **purely
optional** and single-service `/ship` is unaffected. When present it is the
authoritative map of service `name` → local `path` (+ optional `test`/`build` command
and default `dependsOnServices`) that the planner and orchestrator use instead of
guessing.

## Rules

1. **Emit an event at every meaningful step.** Start of work, key decision, handoff,
   blocker, completion. The dashboard is only as good as the events you emit.
2. **One line per summary.** Humans read summaries, not diffs.
3. **Never hand-write run.json or messages.jsonl** — always go through `pipe.py`.
4. **Reference, don't paste.** Large output (plans, diffs, findings) goes into its
   own pipeline file; the event carries a `ref` to it.
5. **Phase order is fixed:** spec → plan → implement → test → review → qa → done.
   Only the orchestrator advances the phase.
