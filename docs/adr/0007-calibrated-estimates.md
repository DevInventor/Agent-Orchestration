# ADR-0007 — Calibrated estimates: finished runs price the planner's minutes

**Status:** accepted · **Date:** 2026-11-18 · **Supersedes:** the first rejected option in ADR-0006

## Context

ADR-0006 gave every run an estimate from fixed rules and rejected pricing it from past
runs. Its stated cost was "fixed rules do not correct themselves": the board would show
estimate against actual, and a human would edit `SIZE_MIN`, `COMPLEXITY_BAND` and
`SUITE_MIN` when drift showed. Nobody did, and a week of real runs showed the drift:

| Run | Rules | Actual work | Off by |
|---|---|---|---|
| groups-run-a-vault | 4h 52m | 2h 05m | ×2.3 over |
| groups-run-b-janus | 7h 48m | 1h 34m | ×5.0 over |
| groups-run-c-portal (running) | implement 14h 36m | 1h 17m for 7 of 21 tasks | — |

Across 23 tasks the median actual was 0.32 of the estimate. Test was 4–7× over: the fix
round count was about right (2 used against 1–2 expected), the price of a round was not.
34 of 46 planned tasks were rated `medium`, so complexity barely separated them.

Two measurement defects sat under the numbers. A task's actual on the board was wall time
from `startedAt` to `doneAt`, which counts the hours a run waits on its owner at a gate or
sits paused. And nothing recorded which models ran the work.

## Decision

1. **The planner's job does not change.** It still reads the change and picks a size, a
   complexity and minutes inside the band; `validate-plan` still enforces the band. The
   planner never sees history and is not asked to pad.
2. **History prices the planner's minutes, in `pipe.py`, at no token cost.** For every
   finished run with a full clock (plan and implement timed), the ratio of actual work to
   the rules' estimate is taken per phase and, from measured tasks, per task size. A factor
   is the median of the log ratios, shrunk toward its parent by a prior: the whole run
   toward 1 (the rules) with the weight of 3 runs, each phase toward the whole run, each
   size toward implement with the weight of 5 tasks. The latest 20 finished runs count.
   Every factor is clamped to ×0.25–×2. With five runs or more, "likely by" uses the 80th
   percentile of how far runs landed from their calibrated figure instead of a flat ×1.25.
3. **It switches on only when it is better.** A backtest re-estimates each finished run
   from only the runs before it and compares the miss with the fixed rules'. Calibration
   is used while it misses by less; otherwise new runs take the rules, and the page and
   `pipe.py calibration` say why.
4. **A run is priced once**, the first time its plan carries an estimate. The factors are
   stamped on `run.json` with the model each role ran on, so the time you planned around
   does not move because another team finished.
5. **A task's actual is work, not wall time.** The tasks in progress at a bus write share
   the next gap the same way the phase clock does: two in one service split it, services
   in parallel each take it whole, and a gap spent waiting on you or paused is no task's.
   Kept in `run.json` (`clock.tasks`), never in `tasks.json`. A task under 2 minutes of work
   was marked in a burst and is not a sample.
6. **One page shows it all**: `/estimates` reads the report `pipe.py` writes beside
   `pipelines/` (`estimates.json`) when a run is planned or finishes, or on
   `pipe.py calibration`. The server only reads it.

## Considered and rejected

- **Reinforcement learning.** It needs a policy that acts and many episodes; there are two
  usable runs. Calibration is the same feedback loop at the size of the data.
- **Showing the planner its own history at plan time.** It would turn the planner's reading
  of the change into a guess at a number, and spend tokens on every plan.
- **Re-pricing a running run when another finishes.** The figure at the gate is what a
  deployment is planned around; it should not drift underneath it.
- **A history ledger file.** The buses are the record already (`prune` keeps them); the
  report is derived from them and can be deleted without loss.
- **Spawning `pipe.py` from the server.** Keeps one direction of flow: `pipe.py` writes,
  the dashboard reads.

## Consequences

- With two runs the correction is deliberately partial: the factor sits between the rules
  and history, and moves further with each finished run. The first runs after this release
  improve it fastest.
- A plan's `minutes` still mean the planner's reading; `eta.planMin` keeps what the rules
  alone would say, and `eta.taskMin` what each task is priced at.
- Per-task samples start with 0.12: older tasks have only wall time and are shown, marked,
  but not used. Until sizes have samples they take the implement factor.
- All runs so far are one project and single-service. Multi-service estimates still rest
  on the chain arithmetic of ADR-0006, scaled.
- The test suite pins `AGENT_ORCHESTRATION_HOME` to a temporary directory at import, so a
  developer's own history cannot move the minutes its scenarios assert.
