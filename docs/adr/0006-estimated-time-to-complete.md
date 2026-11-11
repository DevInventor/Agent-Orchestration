# ADR-0006 — Estimated time to complete: the planner sizes once, the bus does the arithmetic

**Status:** accepted · **Date:** 2026-11-11

## Context

A run gave no answer to "when will this be ready?", so a deployment could not be planned
around it. Two further defects surfaced while looking:

- **Finished work showed as unfinished.** A run only became `done` when the orchestrator
  remembered `phase done` after QA. Six of 27 real workstreams were frozen mid-run because
  the session ended first, one of them at "implement, 33%" with every service through QA.
- **`done` meant two things.** QA green and "deployed" were the same state, and the
  pipeline cannot see a deployment.

Measured once across those 27 buses (gaps over 15 minutes removed): a finished run took a
median of 4h 24m of work, planning 28m, about 8m of implementation per task. Test time
ranged from 16m to over 6h, and elapsed time was dominated by waiting on a human.

## Decision

1. **The planner estimates each task once, at plan time.** A size (S/M/L) by scope sets a
   baseline; a complexity (low/medium/high) by named signals sets a band; the planner picks
   minutes inside the band. `validate-plan` enforces the band. The rules are general and
   live in `skills/estimation-rules`.
2. **No agent reports timing and none is asked for a re-estimate.** `save_run` sorts the
   gap since the previous bus write into work, waiting (at a gate or blocked) or paused (a
   silence over 15 minutes while `running`). The estimate is recomputed from `plan.json`
   and `tasks.json` on the same write. Tracking costs no tokens.
3. **Time on the clock, not total effort.** Services that do not depend on each other run
   side by side, so a phase costs its longest chain through `dependsOnServices`.
4. **Two figures:** expected, and "likely by" (one more fix round plus a quarter of the
   work left). Both are shown as a duration and as a local clock time. Waiting and paused
   time push the clock time out and are shown as their own figure.
5. **Two finish states.** *Work completed* is set by a green whole-run `qa-check`, which
   also records the human's remaining steps on the run. *Completed* is a human's stamp
   (`completed.json` beside the bus, from the hall's one button or `pipe.py complete`).
6. **The run's phase follows its services** once all of them have moved on, forward only
   and never to `done`.

## Considered and rejected

- **Pricing sizes from past runs, with an automatic correction factor.** Rejected by the
  owner: estimates should come from the planner's reading of the change under fixed
  rules, not from history. The cost is stated below.
- **Re-estimating with the LLM at each phase change.** Costs tokens on every run for a
  figure the bus can already derive.
- **Detecting deployment from git.** A merge is not a deploy, and several real runs were
  QA green, unmerged and undeployed on purpose.
- **Tickable human steps.** The owner asked for a read-only list and one button.

## Consequences

- Fixed rules do not correct themselves. The board shows estimate against actual per phase
  and per task so drift is visible; changing a figure is an edit to `SIZE_MIN`,
  `COMPLEXITY_BAND` or `SUITE_MIN` in `pipe.py` and the matching table in the skill.
- A plan written before this ADR carries no minutes, so its run shows no estimate.
- Phases are costed one after another: a service that finishes testing early is not
  credited with starting review early. Multi-service estimates lean long, not short.
- Every event now also writes `run.json` (to move the clock), under the existing lock.
- A human judgement that fails after a green `qa-check` has to move the run back
  (`phase qa`, then `set-status blocked`); green is no longer a state you can sit in.
