---
name: pipeline-protocol
description: The shared coordination contract for the Agent-Orchestration pipeline. Consult whenever an agent (planner, coder, tester, reviewer, or the orchestrator) needs to read from or write to the ./pipeline bus, emit a status/handoff event, update the phase or progress bar, or understand the file layout every agent shares. Use this before touching any file under ./pipeline.
---

# Pipeline protocol

All four agents are stateless subagents. They never talk to each other directly â€”
they coordinate **only** through files under `<repo>/pipeline`. Treat this directory
as a shared message bus. Always mutate it through the `pipe.py` CLI so writes stay
atomic and the message log never corrupts under concurrent agents.

`pipe.py` lives at `${CLAUDE_PLUGIN_ROOT}/scripts/pipe.py`. Run it from the repo root
(it auto-locates `./pipeline`).

## File layout

```
pipeline/
â”œâ”€â”€ run.json          # single source of truth for the dashboard header
â”œâ”€â”€ spec.md           # normalized feature spec (orchestrator writes)
â”œâ”€â”€ index.md          # planner's lightweight codebase index (shared understanding)
â”œâ”€â”€ plan.md           # planner output, human-readable
â”œâ”€â”€ plan.json         # planner output, structured: tasks, files, acceptance criteria
â”œâ”€â”€ tasks.json        # the task board  -> right panel
â”œâ”€â”€ messages.jsonl    # append-only event log  -> left panel (agent comms)
â”œâ”€â”€ code/
â”‚   â”œâ”€â”€ changes.json  # coder: {summary, files:[...], notes}
â”‚   â””â”€â”€ diff.patch    # coder: unified diff of the change (git diff)
â”œâ”€â”€ test/
â”‚   â”œâ”€â”€ scenarios.json# tester: use-case + dataflow scenarios
â”‚   â””â”€â”€ results.json  # tester: {iteration, passed, failed, failures:[...]}
â”œâ”€â”€ review/
â”‚   â”œâ”€â”€ review.md     # rendered from review.json by `pipe.py review --from`
â”‚   â””â”€â”€ review.json   # reviewer findings: [{severity, file, line, note, planRef}]
â””â”€â”€ status/
    â””â”€â”€ summary.md     # QA/orchestrator: completed + current task  -> right panel
```

### Multi-service runs (>1 service): per-service artifact namespace

The flat `code/`, `test/`, `review/` dirs above are the **single-service** layout and
stay exactly as-is for a plain `/ship`. When a run builds more than one service, each
service's coder/tester/reviewer batch writes its artifacts under a per-service namespace
so concurrent same-batch subagents never clobber a shared file:

```
pipeline/services/<service>/
â”œâ”€â”€ code/{changes.json,diff.patch}
â”œâ”€â”€ test/{scenarios.json,results.json}
â””â”€â”€ review/{review.md,review.json}
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
  "slug": "009-messaging-hub",
  "branch": "feature/009-messaging-hub",
  "repos": [ { "service": "api", "repo": "/abs/OpenCRM",
               "worktree": "/abs/repos/wt-009-messaging-hub/api",
               "branch": "feature/009-messaging-hub", "base": "develop" } ],
  "mode": "worktree",
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

`slug`, `branch`, `repos` and `mode` are present only when the bus was created with
`init --slug` â€” the workstream half of the record. `branch` is fixed at `init` and is the
same string in every repository; only `worktree add` writes `repos[]`, and it takes no
branch argument, so nothing can introduce a second name.

`status: awaiting_approval` is the finalize gate (plan done, waiting for the user).
`services` is present only in a multi-service run â€” one entry per service, written by
`pipe.py svc`. The header `phase`/`progressPct`/`loop` stay the **macro** run; each
service's granular phase and fix-loop live under its `services` entry.

## messages.jsonl (one JSON object per line)

```json
{ "ts":"ISO-8601", "runId":"run-YYYYmmdd-HHMMSS-xxxx",
  "agent":"planner|coder|tester|reviewer|orchestrator",
  "type":"status|handoff|finding|question|result|error",
  "phase":"plan", "summary":"one human-readable line",
  "service":"oauth_v3.8.0 (optional; multi-service runs)",
  "detail":"optional longer text", "ref":"pipeline/plan.md" }
```

`runId` is stamped by `pipe.py` â€” never write it yourself. It exists because this log is
**append-only and never rotated**: one long-lived bus accumulates every run it has ever
seen, and without the stamp the dashboard cannot tell this run's events from the previous
feature's. The dashboard filters the feed to the active `runId`.

Keep `summary` to one line â€” it is what a human skims in the dashboard. Put anything
long in `detail` or in a referenced file via `ref`.

## The CLI you will actually call

```bash
PIPE="python3 ${CLAUDE_PLUGIN_ROOT}/scripts/pipe.py"

$PIPE init --feature "..."                 # orchestrator only, once
$PIPE phase plan                           # advance the phase (recomputes progress)
$PIPE agent coder                          # set the active agent
$PIPE progress 60                          # optional manual progress override
$PIPE loop --count 2 --max 5               # coder<->tester loop counter (single-service)
$PIPE set-status awaiting_approval         # run-level status (finalize gate, blocked, runningâ€¦)
$PIPE task add --id T1 --title "..." --owner coder [--service oauth_v3.8.0]
$PIPE task update --id T1 --status done [--service oauth_v3.8.0]
$PIPE event --agent coder --type handoff --summary "..." [--detail "..."] [--ref path] [--service oauth_v3.8.0]
$PIPE svc --name oauth_v3.8.0 --phase test --loop-count 2 --loop-max 5 \
          --agent tester --status running --passed 8 --failed 1   # per-service header state
$PIPE status                               # print run.json
$PIPE config                               # load+validate optional agent-orchestration.config.json
$PIPE review --from findings.json [--service oauth_v3.8.0]   # reviewer only: validate + persist
$PIPE slug --spec docs/specs/009-messaging-hub/design.md     # the workstream's name
$PIPE worktree add --service api --repo /abs/repos/OpenCRM   # materialise the branch
$PIPE finish 009-messaging-hub [--apply [--teardown]]        # plan / perform the merge home
```

The reviewer writes `review/{review.json,review.md}` **itself** through `review --from`,
which validates the payload before writing anything and emits the `finding` event. Nobody
retypes findings on its behalf.

`--service` and `svc` are **optional/additive**: omit them and behavior is identical to
the original single-service pipeline. Use them only in a multi-service run.

## Optional service registry â€” `agent-orchestration.config.json`

A user may drop a `agent-orchestration.config.json` at their repos root declaring the services
they work with and where those repos live locally. `$PIPE config` walks up to find it,
validates it, and prints normalized JSON:

```json
{ "configured": true, "reposRoot": "/abs/repos",
  "services": [ { "name": "oauth", "path": "/abs/repos/oauth_v3.8.0",
                  "test": "mvn -q test", "build": null, "dependsOnServices": [] } ] }
```

When absent it prints `{"configured": false, "services": []}` (exit 0) and the pipeline
falls back to discovering service dirs by indexing â€” so the registry is **purely
optional** and single-service `/ship` is unaffected. When present it is the
authoritative map of service `name` â†’ local `path` (+ optional `test`/`build` command
and default `dependsOnServices`) that the planner and orchestrator use instead of
guessing.

## Rules

1. **Emit an event at every meaningful step.** Start of work, key decision, handoff,
   blocker, completion. The dashboard is only as good as the events you emit.
2. **One line per summary.** Humans read summaries, not diffs.
3. **Never hand-write run.json or messages.jsonl** â€” always go through `pipe.py`.
4. **Reference, don't paste.** Large output (plans, diffs, findings) goes into its
   own pipeline file; the event carries a `ref` to it.
5. **Phase order is fixed:** spec â†’ plan â†’ implement â†’ test â†’ review â†’ qa â†’ done.
   Only the orchestrator advances the phase.

## Framework bindings

Each phase invokes one named skill and only that one - the table is in
`docs/orchestration-runbook.md` and the reasoning in `docs/adr/0002-framework-adoption.md`.
The framework supplies the method; the agent definition supplies this project's flavour,
and **where they differ the local rule wins** - this bus contract is not negotiable.

Never load the framework wholesale. `superpowers` is pinned at 6.4.1 and the suite fails
if the installed version differs.
