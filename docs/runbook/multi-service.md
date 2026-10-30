# Runbook part: the multi-service path

Read this from `docs/orchestration-runbook.md` §1c, after the finalize gate, when the plan
has more than one service. Everything there still applies: `$PIPE`, the framework bindings, and the
guardrails. Re-read this file at the top of every fix iteration and after any compaction.

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
   **Spawn one coder per ACTIVE service, all in a single message.** While a service
   has unbuilt tasks it is in mode A, and its coder gets only what
   `$PIPE next --service <svc>` names - at most two tasks; **repeat coder batches until
   `next` is empty for every service in the batch**, then go to its tester batch. A
   fresh coder per pair keeps each context small: one coder that carried a whole service
   grew to 438k tokens. Empty `next` with a non-empty `remaining` means it waits on
   another service's task; if no service in a batch gets a task, that is a dependency
   cycle - set `status: blocked` and surface it. Once its tasks are built, a re-spawn is
   mode B (fix only that service's failing results; from `K_svc >= 2` with
   `model: "opus"`, ADR-0003). Each coder is scoped to its own service dir, is handed
   **that service's base branch** (from `run.json`'s `repos[]` entry, else the repo's
   current branch) so it can commit each task and write `diff.patch` as
   `git diff <base>...HEAD`, writes under `pipeline/services/<svc>/code/`, and tags
   tasks/events `--service <svc>`. **Await all.**
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

**Two isolation modes, and which one you are in.** A multi-service plan isolates services
from each other by giving each its own directory, resolved from the registry — that alone
needs no worktrees, because separate service dirs cannot collide on files or `git diff`.
Worktrees isolate one *workstream* from another, so two features can touch the same
repository at once; that is what `pipe.py worktree` and `run.json`'s `mode` are for, and
they are created at the finalize gate.

`init` stamps `mode: "worktree"` on every run with a slug, including runs that never call
`worktree` — read it as the default intent, not as proof that a container exists; `repos[]`
is what records one. **If you already have worktrees, the pipeline will not fight you**:
point the run at them with `in-place` at the finalize gate, or let `worktree add` reuse an
existing checkout — it prints `worktree already present, reusing` rather than failing, and
attaches to the existing branch rather than inventing a variant of the name.

Then go back to the runbook for the QA gate (§5), which aggregates across all services.

