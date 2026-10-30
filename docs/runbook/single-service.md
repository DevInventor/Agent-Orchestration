# Runbook part: the single-service path

Read this from `docs/orchestration-runbook.md` §1c, after the finalize gate, when the plan
has exactly one service. Everything there still applies: `$PIPE`, the framework bindings, and the
guardrails. Re-read this file at the top of every fix iteration and after any compaction.

### 2. Implement  (phase: implement)
1. `$PIPE phase implement && $PIPE agent coder`.
2. **One fresh coder per two tasks.** Ask `$PIPE next`; it answers
   `{"next": [ids], "remaining": [ids]}` in plan order with dependencies met. Spawn the
   **coder** subagent (`agents/coder.md`) with exactly those ids, the plan, **and the base
   branch it merges home to** — `run.json`'s `repos[]` entry for its service if the run
   has one, else the repo's current branch. It implements them in the actual repo,
   **commits each completed task** (`T#: ...`), adds to `pipeline/code/changes.json`,
   writes `diff.patch` as `git diff <base>...HEAD`, and marks them `done`. Await it, then
   ask `next` again; stop when `next` is empty. Empty `next` with a non-empty `remaining`
   means a dependency cycle or a missing task: set `status: blocked` and surface it.
   Never hand one coder the whole service: a coder's context is re-read on every call,
   and one that carried five tasks grew to 438k tokens.

### 3. Test + fix loop  (phase: test)  — max 5 iterations
This is the test-driven bug-fixing loop. Track it with `$PIPE loop --count K --max 5`.

```
K = 1
loop:
  $PIPE phase test && $PIPE agent tester && $PIPE loop --count K --max 5
  spawn tester  -> writes pipeline/test/scenarios.json + results.json
  if results.failed == 0:
      break                      # green
  # Ask the bus for the verdict; do not count yourself. --bump-loop increments where
  # the number is kept and answers `blocked`, so a miscount cannot loop past max (P1).
  $PIPE svc --name <svc> --bump-loop      # -> {"loop":{"count":K,"max":5},"blocked":bool}
  if blocked:
      $PIPE event --agent orchestrator --type error \
        --summary "Fix budget spent, still N failing - escalating to user"
      mark status blocked; STOP the loop and report
  if K >= 2:
      # ADR-0002: iteration 2 must change strategy, not repeat iteration 1. That is how
      # a budget of five gets spent producing five variations of the same wrong fix.
      # ADR-0003: and a stronger model - the coder's default is sonnet.
      spawn the coder with superpowers:systematic-debugging and model: "opus"
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

Then go back to the runbook for the QA gate (§5).
