# Orchestration runbook (plan → QA)

Shared run-book for the `/ship` family of skills. This is a **reference doc, not an
invocable skill** — `skills/ship` and `skills/ship-from-spec` each prepare the spec
their own way, then hand off to this runbook from the Plan phase onward. Everything
below is identical regardless of where the spec came from.

You are the **conductor**. You do not plan, write, test, or review yourself — you
spawn the four specialist subagents (via the Task tool) in sequence, move state
through the shared `./pipeline` bus, and make the routing decisions between phases.

Read and follow `${CLAUDE_PLUGIN_ROOT}/agents/team-rules.md`.
Read the **pipeline-protocol** skill first if you have not this run. Set:

```bash
PIPE="python3 ${CLAUDE_PLUGIN_ROOT}/scripts/pipe.py"
```

## Precondition (your entry skill has already done this)

Before you reach this runbook, the entry skill has run `$PIPE init` and populated
`pipeline/spec.md` with crisp, testable acceptance criteria. If `pipeline/spec.md`
is missing or empty, stop and go back to the entry skill's spec step.

Your entry skill has also **started the dashboard** in the background and told the user
its URL (http://localhost:4600). If it did not — or if the background process is gone —
start it now before planning, because nothing else will:

```bash
node "${CLAUDE_PLUGIN_ROOT}/ui/server.js" --pipeline "$(pwd)/pipeline"   # background call
```

Then begin at the Plan phase.

> **Emit events or the run is invisible.** The dashboard reads only what agents write to
> the bus. A phase that emits nothing renders identically to a phase that has died — and
> the dashboard now flags any run whose `updatedAt` is older than 3 minutes while its
> status is still `running` as **stale**. If a subagent is doing long work, have it emit a
> `status` event as it goes rather than only on completion.

## Map onto the superpowers workflow

This pipeline is the spec → plan → subagent-driven development → testing →
test-driven bug-fixing → QA → done loop. **If the `superpowers` plugin is installed**
(check the available skills/commands), prefer delegating the matching stage to its
workflow and let this orchestrator handle the agent hand-offs and the pipeline bus
around it. If it is not installed, run each phase natively with the agents below.
Either way the phase names and the bus contract stay the same.

## The run, phase by phase

### 1. Plan  (phase: plan)
1. `$PIPE phase plan && $PIPE agent planner`.
2. Spawn the **planner** subagent (see `agents/planner.md`). Hand it: the repo root,
   the path to `pipeline/spec.md`, and the instruction to index the codebase and
   produce `plan.md` + `plan.json` + seed `tasks.json`. Its `plan.json` groups tasks
   by `service` and declares each service's `dependsOnServices`.
3. When it returns, sanity-check that `pipeline/plan.json` exists and has tasks +
   acceptance criteria + a `services` list. If not, re-run once with corrective
   feedback, else mark `status: blocked` and surface to the user.

### 1b. FINALIZE GATE  (still phase: plan — do NOT add a new phase)
The plan phase does not advance to implement until the user approves. This is a hard
stop, not a pause you talk through.
1. Present the plan to the user as a **numbered list grouped by service**, each service
   with its tasks and any `dependsOnServices`. Keep it skimmable.
2. `$PIPE set-status awaiting_approval` and, for visibility,
   `$PIPE event --agent orchestrator --type question --summary "Plan ready — reply 'finalize' to start, or edit scope"`.
3. **END YOUR TURN.** Write no code, spawn no coder. Wait for the user.
   - The user may edit scope (drop/add tasks or services). Apply their edits to
     `plan.json` + the task board, re-present, and stay at the gate.
   - Only when the user replies **finalize** (or equivalent go-ahead) do you continue.
4. On finalize: **rehydrate** — re-read `pipeline/run.json` and `pipeline/plan.json`
   (you are likely a fresh turn), `$PIPE set-status running`, then proceed to §2.

### 1c. Choose the execution path (after finalize)
Count distinct `service` values in `plan.json`.
- **Exactly one service → Single-service path (§2–§5 below), unchanged.** This is the
  original behavior; a run that touches one service uses today's flow with no
  per-service machinery.
- **More than one service → Multi-service path (§M).** Skip §2–§5; jump to §M.

## Single-service path  (plan has exactly 1 service — the original flow)

### 2. Implement  (phase: implement)
1. `$PIPE phase implement && $PIPE agent coder`.
2. Spawn the **coder** subagent (`agents/coder.md`) with the plan. It implements the
   tasks in the actual repo, writes `pipeline/code/changes.json` + `diff.patch`, and
   marks tasks `done` as it goes.

### 3. Test + fix loop  (phase: test)  — max 5 iterations
This is the test-driven bug-fixing loop. Track it with `$PIPE loop --count K --max 5`.

```
K = 1
loop:
  $PIPE phase test && $PIPE agent tester && $PIPE loop --count K --max 5
  spawn tester  -> writes pipeline/test/scenarios.json + results.json
  if results.failed == 0:
      break                      # green
  if K >= 5:
      $PIPE event --agent orchestrator --type error \
        --summary "Reached 5 fix iterations, still N failing — escalating to user"
      mark status blocked; STOP the loop and report
  # route failures back to the coder
  $PIPE agent coder
  spawn coder with pipeline/test/results.json failures -> fix only those
  K = K + 1
```

On the first test phase the tester **also authors** the scenario suite (use cases +
application dataflow paths), not just runs it. On re-runs it re-executes and reports
deltas.

### 4. Review  (phase: review)
1. `$PIPE phase review && $PIPE agent reviewer`.
2. Spawn the **reviewer** subagent (`agents/reviewer.md`). It cannot modify the repo:
   its agent definition grants no `Write` and no `Edit`. It compares the implementation
   against `plan.json`, and uses the `ponytail` review skill (`/ponytail.review` or the
   `ponytail` skill) to strip codebase noise and focus on the real diff. It **persists
   its own findings** through `$PIPE review --from <file>` — which writes
   `pipeline/review/review.{json,md}` and emits the `finding` event — and returns you a
   one-line summary. Do not retype its findings; read `pipeline/review/review.json`.
3. Routing: if there are **blocking** findings, send them back to the coder (this
   reuses the same fix budget — do not exceed the total of 5 coder fix iterations
   across test+review combined). Re-test after any code change. If only non-blocking
   notes remain, annotate and proceed.

## §M. Multi-service path  (plan has >1 service) — phase-batched, top level

**You (the orchestrator) drive everything from the top level.** A nested subagent can
spawn children and write files, but a **mid-level agent cannot await its own children**
in this build (proven) — so there is **no per-service runner**. Instead you run the
pipeline in **batches**: every coder/tester/reviewer is a child *you* spawn directly, so
you always await at the top level, the one depth where await works. Put all subagents of
a batch **in one message** (they run concurrently); await the whole batch before the next.

Per-service state lives in `run.services[<svc>]` (`status`, `loop.count`,
`loop.max=5`, `passed`, `failed`). The macro header `phase` stays `implement` through
the build.

### Setup
1. `$PIPE phase implement`.
2. **Resolve service dirs from the registry.** Run `$PIPE config`. If `"configured":
   true`, use each service's absolute `path` as its working directory and its optional
   `test`/`build` command; hand these to that service's coder/tester so they run in the
   right repo with the right commands. If `"configured": false`, the service `name` is
   itself the dir under the repos root (today's behavior).
3. Seed every service: `$PIPE svc --name <svc> --status pending --loop-max 5`.

### Readiness — `dependsOnServices` is the batch-admission gate (dependency waves)
A service is **eligible** for a coder batch only when **every** name in its
`dependsOnServices` has `status: done` in `run.services`. So all independent services
(`dependsOnServices: []`) enter **wave 1** together; a dependent service is **held out**
of wave 1 and only admitted to a **later** batch once its dependencies are `done`.
Re-check eligibility after every tester batch (services may have just gone `done`).

### The batched loop  (repeat until every service is `done` or `blocked`)
1. **Coder batch.** `ACTIVE` = every service that is *eligible* and not yet
   `done`/`blocked`. For each, `$PIPE svc --name <svc> --phase implement --agent coder`.
   **Spawn one coder per ACTIVE service, all in a single message.** First time for a
   service = mode A (implement its task slice); a re-spawn = mode B (fix only that
   service's failing results). Each coder is scoped to its own service dir, writes under
   `pipeline/services/<svc>/code/`, and tags tasks/events `--service <svc>`. **Await all.**
2. **Tester batch.** For each service just coded:
   `$PIPE svc --name <svc> --phase test --agent tester --loop-count K_svc`, where
   **`K_svc` is that service's own iteration counter** (per service, never a shared batch
   number). **Spawn one tester per service in a single message**, each working in that
   service's resolved dir, using its registry `test` command if one was configured
   (else the tester infers the runner from the repo), and writing
   `pipeline/services/<svc>/test/{scenarios,results}.json`. **Await all.**
3. **Evaluate each service independently** (per-service bookkeeping, not per-batch):
   - `failed == 0` → `$PIPE svc --name <svc> --status done --passed P --failed 0`.
     **The service drops out of every future coder/tester batch.**
   - `failed > 0` and `K_svc < 5` → bump only its counter
     (`$PIPE svc --name <svc> --loop-count <K_svc+1>`); it stays ACTIVE and is
     re-spawned in the **next** coder batch with just its own failures. Other services'
     counters are untouched.
   - `failed > 0` and `K_svc >= 5` → `$PIPE svc --name <svc> --status blocked`; it drops
     out; record it for the QA gate.
   Then re-check readiness and admit any newly-eligible dependents to the next wave.

Because each service owns its `loop.count` and leaves the moment it is green, a fast
service (green at iter 1) is **never** re-spawned while a slow one keeps iterating — the
budget of 5 is enforced **independently per service**, not as a shared batch count.

### Review batch
When all services are `done`/`blocked`: `$PIPE phase review`. **Spawn one reviewer per
`done` service in a single message.** Each reviewer persists its own findings with
`$PIPE review --from <file> --service <svc>`, which writes
`pipeline/services/<svc>/review/{review.md,review.json}` and emits the `finding` event
tagged for that service; you get one line back. Blocking findings route that service
back into a coder batch (counting against its same budget of 5), then re-test and
re-review that service only.

Worktrees are intentionally not used: separate service dirs can't collide on files or
`git diff`.

Then continue to the QA gate (§5), which aggregates across all services.

### 5. QA gate  (phase: qa)
1. `$PIPE phase qa`.
2. `$PIPE qa-check` — the mechanical gates are an exit code, not a reading exercise: it
   fails on any `blocking` finding in the current `review.json`, any task not `done`,
   and any service whose `test/results.json` is failing or missing, across every service
   in `run.services`. Non-zero prints one line per failed gate; fix those before
   continuing. Then judge what it cannot: does the work actually meet
   `pipeline/spec.md`'s acceptance criteria, and is any service `blocked`?
3. Write `pipeline/status/summary.md`: what shipped (grouped by service in a
   multi-service run), per-task status, per-service test summary and fix-loop count,
   review disposition, and anything deferred or blocked.
4. If all gates pass: `$PIPE phase done`. Otherwise `$PIPE set-status blocked` and
   explain which service(s) blocked and why.

### 6. Report
Give the user a tight summary: feature, tasks completed, test result (and how many
fix iterations it took), review disposition, and the path to `status/summary.md`.

## Guardrails
- Fix-loop budget is **per service**: 5 iterations each (failing tests + blocking
  review findings share that one budget). In a single-service run that is simply the
  original global cap of 5. One service exhausting its 5 never consumes another's.
  Never loop unbounded.
- Every subagent gets: the repo root, the relevant pipeline file paths, and a
  reminder to emit events via `pipe.py`. Pass paths, not pasted contents.
- If any subagent reports it cannot proceed, stop, set `status: blocked`, emit an
  `error` event, and hand control back to the user — do not silently retry forever.
- Keep the user informed with short check-ins between phases; the dashboard has the
  detail.
