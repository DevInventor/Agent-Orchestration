---
name: estimation-rules
description: General rules for estimating how long a planned task takes an agent team - a size by scope, a complexity by named signals, and minutes inside a band - plus how those figures become phase estimates and a time on the clock, and how finished runs calibrate them. Use when writing or reviewing a plan's task estimates, when validate-plan rejects a task's size, complexity or minutes, or when asked why a run's estimated time to complete is what it is.
---

# Estimation rules

The planner estimates every task once, while it writes the plan. After that nothing asks
an agent how long is left: `pipe.py` does the arithmetic on the bus (ADR-0006) and prices
it from finished runs (ADR-0007, below). So the whole estimate is only as good as the
three fields below. They refer to things every plan has, so they hold in any project.

## Per task: four fields in `plan.json`

| Field | Value |
|---|---|
| `size` | `S`, `M` or `L`, by scope |
| `complexity` | `low`, `medium` or `high`, by the signals below |
| `minutes` | your figure, inside the band for that size and complexity |
| `reason` | one line naming the signals; required when complexity is not `low` |

### Size sets the baseline

| Size | Scope | Baseline |
|---|---|---|
| S | One file, or a mechanical change with no new behaviour | 5 |
| M | Two to four files, one new behaviour with its tests | 10 |
| L | Five or more files, or several behaviours | 25 |

A task larger than L is two tasks. Split it.

### Complexity raises it

Count the signals the task really has:

- It changes a contract or interface that other code or another service consumes.
- It carries a data migration or a schema change.
- It touches security, authentication or concurrency logic.
- The code it changes has no existing tests.
- Many callers depend on it (check with `trace_path`, do not guess).
- The requirement is unclear, or the area is legacy.

| Complexity | Signals | Minutes must be |
|---|---|---|
| low | none | exactly the baseline |
| medium | one or two | 1.5 to 2 times the baseline |
| high | three or more | 2 to 3 times the baseline |

Choose the figure inside the band from what you saw in the code. `pipe.py validate-plan`
rejects a task with a missing field or minutes outside its band.

## Per service: one field

`suite` on each entry of `services[]`: `fast` (about 2 minutes), `medium` (about 10) or
`slow` (about 25), judged from the service's test command. Omitted means `medium`.

## What the pipeline derives (you do not write these)

| Phase | Estimate |
|---|---|
| Spec | 5 |
| Planning | 10, plus 1.5 per task |
| Implement | Task minutes summed per service, then the longest chain through `dependsOnServices` |
| Test and fix, per service | 15 for scenarios, plus 5 per medium task and 10 per high task, plus the suite for each run, plus 15 per fix round |
| Fix rounds expected, per service | 1, plus 1 if it has a high task, plus 1 if another service depends on it (at most 3) |
| Review, per service | 10, plus 1 per task, plus 3 per high task |
| QA | 10, plus 5 for each service after the first |

Services that do not depend on each other run side by side, so test and review cost the
slowest service, not the sum. "Likely by" is the expected figure plus one more fix round
and a quarter of the work left.

So dependencies are part of the estimate: declare `dependsOnServices` only for a real
ordering constraint. A dependency that is not real makes the run look longer than it is.

## Calibration: what finished runs do to your figures (ADR-0007)

Your minutes are kept as you wrote them. When the plan first carries an estimate, `pipe.py`
prices it from the runs that finished before it: each phase, and each task size, is
multiplied by the factor those runs showed (actual work over the rules' estimate),
pulled toward 1 while there are few of them and clamped to ×0.25–×2. It is used only
while a backtest says it beats the rules; otherwise the run takes the rules above.

- **Do not pad or shave your minutes to correct for history.** Calibration already does,
  and a figure bent to fit it is counted twice. Size what you read in the code.
- **Rate complexity by the signals, not by habit.** Most tasks rated `medium` tells the
  pipeline nothing; a `low` task with no signals is a true `low`.
- `pipe.py calibration` prints the factors, the backtest and every run measured;
  `/estimates` in the dashboard shows the same. Actual there is work only: time waiting
  on you and time paused are never counted.

## Example

A task changes the login contract that `sso` and `janus` consume and adds a schema change,
across six files.

```json
{ "id": "T3", "service": "oauth", "title": "Per-admin passkey login contract",
  "size": "L", "complexity": "medium", "minutes": 45,
  "reason": "contract consumed by sso and janus, plus a migration" }
```

Size L gives 25. Two signals make it medium, so the band is 37.5 to 50, and 45 is the
planner's call. In its service the task adds 5 minutes of test scenarios.
