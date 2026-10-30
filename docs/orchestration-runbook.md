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
PY=$(python3 -c 'import sys;print(sys.executable)' 2>/dev/null || command -v python)
PIPE="$PY ${CLAUDE_PLUGIN_ROOT}/scripts/pipe.py --root <the bus path from the entry skill>"
```

Your entry skill already resolved `$PY` — reuse it. Resolve it again only if you are
resuming a run in a fresh shell. `command -v python3` is **not** enough: on Windows the
Store alias stub is on PATH and only fails when it runs. **Hand the finished `$PIPE`
string to every subagent you spawn**; their cheatsheets say to use the one you gave
them, so this shim lives here and in the two entry skills, nowhere else.

## Precondition (your entry skill has already done this)

Before you reach this runbook, the entry skill has derived the workstream's **slug**,
run `$PIPE init --slug`, announced the branch `feature/<slug>`, and populated
`<bus>/spec.md` with crisp, testable acceptance criteria. If `spec.md` is missing or
empty, stop and go back to the entry skill's spec step.

**The bus path comes from the entry skill, not from your cwd.** `init --slug` puts it
under the fixed pipelines root, so `./pipeline` is the wrong answer. Keep `--root <bus>`
baked into `$PIPE` and **pass the absolute bus path to every subagent you spawn**, with
the pipeline file paths they need spelled out under it.

Your entry skill has also **started the dashboard** in the background and told the user
the URL it printed (4600, or the next free port). If it did not — or if the background process is gone —
start it now before planning, because nothing else will:

```bash
node "${CLAUDE_PLUGIN_ROOT}/ui/server.js"   # background call; scan mode — no --pipeline
```

Scan mode serves the hall at `/` and each run's board at `/r/<slug>`; `--pipeline`
would lock the server into the legacy single-run page. If `/api/hall` already answers
on 4600, a dashboard is running — reuse it instead of starting another.

**Give back finished worktrees, once per run.** A run ends at `phase done`, and nothing
else ever removes its worktrees, so do it here, before planning:

```bash
$PIPE prune --apply
```

It removes a worktree only when its workstream is finished (`done`, or archived by
`finish`), the tree has no uncommitted changes, and the branch is merged into its base or
pushed to a remote. It never deletes a branch, never touches a running workstream, and
prints why it kept anything it kept. Relay any `keeping` lines to the user in one line;
they are not errors and do not block this run.

Then begin at the Plan phase.

> **Emit events or the run is invisible.** The dashboard reads only what agents write to
> the bus. A phase that emits nothing renders identically to a phase that has died — and
> the dashboard now flags any run whose `updatedAt` is older than 3 minutes while its
> status is still `running` as **stale**. If a subagent is doing long work, have it emit a
> `status` event as it goes rather than only on completion.

## Framework bindings  (ADR-0002)

Each phase invokes **one named skill**, and only that one. The framework supplies the
method; the agent definition supplies this project's flavour, and **where they differ the
local rule wins** — the bus contract is not negotiable.

| Phase | Who | Skill |
|---|---|---|
| spec gate | you + orchestrator | `grilling` (`grill-with-docs` when the decision deserves an ADR) |
| plan | planner | `superpowers:writing-plans` |
| finalize gate | you + orchestrator | `grilling` |
| implement | coder | `superpowers:executing-plans` |
| test | tester | `superpowers:test-driven-development` |
| fix loop at K≥2 | coder | `superpowers:systematic-debugging` |
| review | reviewer | `ponytail` review skill |
| findings returned | coder | `superpowers:receiving-code-review` |
| qa gate | orchestrator | `superpowers:verification-before-completion` |
| finish | orchestrator | `superpowers:finishing-a-development-branch` |
| the whole run | orchestrator | `superpowers:subagent-driven-development` |

`subagent-driven-development` is **yours alone** — it is the largest skill in the set and
the most duplicative of this runbook, so it loads once per run, never once per spawn.

**Never load the framework wholesale.** Invoke the skill bound to the phase you are
entering, at the moment you enter it. `superpowers` is pinned at **7.0.0**; the suite fails
if the installed version differs, because an upstream change alters how every agent works.

If a skill is genuinely unavailable, run the phase natively with the agent below and say so
in an event — the phase names and the bus contract are unchanged either way.

## The run, phase by phase

### 1. Plan  (phase: plan)
1. `$PIPE phase plan && $PIPE agent planner`.
2. Spawn the **planner** subagent (see `agents/planner.md`). Hand it: the repo root,
   the path to `pipeline/spec.md`, and the instruction to index the codebase and
   produce `plan.md` + `plan.json` + seed `tasks.json`. Its `plan.json` groups tasks
   by `service` and declares each service's `dependsOnServices`.
3. When it returns, **`$PIPE validate-plan`**. This replaces the old "sanity-check that
   plan.json has tasks + criteria + services" — that was an LLM judgement standing where a
   check belongs, and two defects came through it (a `criteriaRef` written as an array
   index, and criteria nothing could join to a task). It refuses a plan with duplicate
   task ids, a task naming a service that is not in `services[]`, a criterion no task
   implements, or a reference by index rather than id. On a non-zero exit, re-run the
   planner once with the exact output as feedback; if it fails again, mark
   `status: blocked` and surface it.

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
   (you are likely a fresh turn), `$PIPE set-status running`, then choose the path (§1c).

### 1c. Choose the execution path (after finalize)
Count distinct `service` values in `plan.json`, then read **one** of these and follow it:
- **Exactly one service:** `${CLAUDE_PLUGIN_ROOT}/docs/runbook/single-service.md`
  (§2 implement, §3 test + fix loop, §4 review): the original linear flow, with no
  per-service machinery.
- **More than one service:** `${CLAUDE_PLUGIN_ROOT}/docs/runbook/multi-service.md`
  (§M): phase-batched from the top level, one fix budget per service.

Both end by sending you back here for the QA gate (§5). Each is short on purpose: **re-read
yours at the top of every fix iteration, and always after a compaction.** A summary that has
dropped the cap of 5 is how a fix loop runs past it.

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

## The operator (optional — only when the plan names an operational task)

Deploying, rebuilding, restarting and diagnosing an environment is nobody's job in
§2–§5 or §M, so it falls to you by default — which puts the logs in the most expensive
context in the run and makes you player and referee on your own QA gate. Spawn the
**operator** subagent (`agents/operator.md`) instead, at the point the plan names the
task. Most runs never do; skip this section entirely when yours doesn't.

- `$PIPE agent operator`, then spawn it with the command to run and the bus path. It
  holds no `Write`/`Edit` and writes no feature code.
- It reports one `event --agent operator --type result` with four fields — command,
  exit code, what changed, what to verify — and is forbidden from concluding success.
  **You call the outcome**, from that report, so the judgement stays in the run's
  narrative instead of a subagent's scrollback.
- **Anything touching a shared environment is gated.** Before spawning it for a deploy,
  arm the gate — `$PIPE wait --for gate --timeout 1800` in a background Bash, or let the
  operator wait itself — and get the user's `finalize` through the dashboard or
  `$PIPE gate --decision finalize`. Assess, then deploy.

## Long commands, and agents the watchdog kills

An agent dies after roughly 600s of **silent output**. A ten-minute `mvn test` or `pytest`
is silent for its whole duration, so the normal shape of a test phase kills the agent
running it. Five agents across two estates have died this way. Telling agents to "emit
status events as they go" does not help: nothing can emit while the build holds the
process.

Hand every agent that runs a build the wrapper instead:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/heartbeat.py --lock build -- <command>
```

It ticks while the command lives, exits with the command's own code, and `--lock`
serialises heavy builds — §M spawns a batch concurrently, which is right for coordination
and wrong for three JVM builds on one box.

**If an agent is killed anyway, resume it rather than re-spawning it.** Sending it a
message restores its full context *and its uncommitted edits*, and it finishes from where
it stopped; two killed agents were recovered this way on a real run. The one limit,
verified: this works only while **your session is still alive**. Once the session ends the
agent is unreachable and its uncommitted work is gone — which is why the commit-early rule
stands regardless.

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
