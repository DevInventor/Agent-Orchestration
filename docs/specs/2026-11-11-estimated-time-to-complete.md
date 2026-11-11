# Estimated time to complete, and two finish states

**Date:** 2026-11-11 · **Decision record:** `docs/adr/0006-estimated-time-to-complete.md`
**Approved mockup (version 3):** https://claude.ai/artifact/34CNu8dA1uWrLFtCgY5LC3

## Why

A run gives no answer to "when will this be ready?", so a deployment cannot be planned
around it. Finished work also showed as unfinished: a run only became `done` if the
orchestrator remembered `phase done`, and "deployed" was not a state at all.

## Read this first: the working tree already holds a first implementation

This spec is not a greenfield build. An uncommitted first pass of everything below is in
the working tree of this repository (`master`, version 0.11.0 unreleased). It was written
in one session and checked by hand; it has **not** been through plan, test and review.

- **Run in place.** A fresh worktree from the last commit would not contain this work, and
  rebuilding it there would conflict with it. At the plan gate the decision is **in-place**.
- **The job is to verify, close the gaps listed under "Remaining work", and harden.** Do
  not rewrite what already meets its criterion. Read the code before planning a task for it.
- Unrelated uncommitted work is also in the tree (design rules, test scenarios, ADR-0003
  to 0005). Leave it alone.

### What exists today

| Area | File | State |
|---|---|---|
| Clock, estimate, band check, auto-completion, `eta`, `complete` | `scripts/pipe.py` | Built; scenario S69 passes |
| Hall payload fields, `POST /api/complete` | `ui/server.js` | Built; no test yet |
| Hall cards, Ready to deploy tab, final button, redrawn cast, office tags and auto-fit | `ui/hall.html` | Built; differs from the mockup (see below) |
| Board: time band, service lanes, inspector tabs, comms filter | `ui/board.html` | Built; close to the mockup |
| Estimation rules | `skills/estimation-rules/SKILL.md` | Written |
| Planner, runbook, protocol skill, glossary, README, config schema | various | Updated |

## Decisions already made (do not reopen)

1. **Work completed** is set by a green whole-run `qa-check`, never by hand. **Completed**
   is a human's stamp after deploying: one button in the hall, or `pipe.py complete`.
2. A work-completed run shows a **read-only** list of four standard steps (merge, deploy,
   verify, close). A project may replace the list with `humanSteps` in its config.
3. The **planner estimates each task once**, at plan time: a size (S, M, L), a complexity
   (low, medium, high) and minutes inside the band those allow. No history pricing and no
   automatic correction. Rules: `skills/estimation-rules/SKILL.md`.
4. **Tracking costs no tokens.** No agent reports timing or re-estimates. `pipe.py` sorts
   elapsed time into work, waiting on you (gate or blocked) and paused (silent over 15
   minutes while running), and recomputes what is left on every bus write.
5. Headline figures are **time on the clock**: parallel services cost their longest
   dependency chain, not the sum.
6. Two figures everywhere: **expected** and **likely by**, each as a duration and as a
   local clock time. Waiting and paused time are shown and push the clock time out.

## Remaining work

### R1. Hall cards match the approved mockup
The real card keeps the old felt table with seats and adds the estimate beneath it. The
approved mockup card is flatter: name and status pill, a compact team row (four characters
with who is active), three figures, the time rail, then the last event or the plan
summary. Bring the real card to the mockup, three per row, without losing: the plan brief
and gate buttons on a plan-gate card, the hide control, the unread dot, the stale and
usage-limit lines, and the link to the board.

### R2. Office matches the approved mockup
Keep the pan and zoom canvas fitted to the screen. Bring the look to the mockup: a shared
table per island with laptops, the redrawn characters at a readable size, the state tag
above each island, and motion that maps to state (typing, hand raised while waiting on
you, shaking when blocked, asleep when finished, empty desks when completed).

### R3. Board
Verify against the mockup and fix what differs. Known gaps: no test covers the lanes, the
inspector or the time band; the board does not refresh its clock figures between bus
writes.

### R4. Tests for what has none
`POST /api/complete` (unknown slug, run not done, stamp written with the run id, a later
wave starts unstamped); the hall payload's estimate fields; `humanSteps` from the config,
including a rejected malformed value; `eta` on a run with no estimate; the 15-minute
pause boundary.

### R5. Documents that the code has moved past
`docs/specs/2026-09-18-multi-pipeline-engine.md` sections 10.3 to 10.6 describe the pixel
cast, the eight-entry motion list and the six-column board. Update them to what ships.
Update `scripts/demo_estate.py` if it builds plans, so demo plans pass `validate-plan`.

## Acceptance criteria

- **AC1** - Given a plan whose task has a size and complexity, when its minutes fall
  outside the band for that pair, then `validate-plan` fails and names the task and band.
- **AC2** - Given a validated plan, when the run reaches implement, then `run.json`
  carries an estimate per phase and the minutes left, with no agent having reported time.
- **AC3** - Given two services where one depends on the other, when the estimate is
  computed, then implement costs their chain; given two independent services, the longer.
- **AC4** - Given a run waiting at a gate, when time passes, then that time is counted as
  waiting on you, the work left does not shrink, and the expected clock time moves out.
- **AC5** - Given a run that says running but has been silent over 15 minutes, when the
  next bus write lands, then the gap is counted as paused, not as work.
- **AC6** - Given every service of a run has moved past the run's own phase, when a
  service is updated, then the run's phase follows them, forward only and never to done.
- **AC7** - Given a whole-run `qa-check` is green, when it exits, then the run is work
  completed, the human's steps are recorded on it, and they are printed.
- **AC8** - Given a work-completed run, when a human presses Mark completed and confirms,
  then the workstream is completed and moves to the Completed tab; given a run that is not
  done, then the request is refused.
- **AC9** - Given a running workstream with an estimate, when the hall is open, then its
  card shows expected and likely-by on the local clock, work left, waiting time and a
  to-scale phase rail, three cards to a row on a wide screen.
- **AC10** - Given the office view, when it opens or the window resizes, then the floor
  fits the screen, can be dragged and zoomed, and each island shows its state tag.
- **AC11** - Given a workstream's board, when it is open, then it shows the time band,
  tasks in service lanes with their time, and an inspector with the selected task's size,
  complexity, reason and estimate against actual, time per phase, and the criteria.
- **AC12** - Given a plan written before this feature, when its run is shown anywhere,
  then no estimate is shown and nothing errors.
- **AC13** - Given `pipe.py eta` on a run with an estimate, then it prints work left,
  expected, likely by, waiting time and estimate against actual per phase.

## Out of scope

- Detecting a merge or a deployment automatically.
- Pricing estimates from past runs.
- Tickable human steps.
- Committing, releasing or publishing 0.11.0. That is the owner's call after QA.

## Constraints

- `ui/` pages render with no network: no webfont or CDN link (tests S39 and S49).
- `scripts/test_pipe.py` is slow and prints only at the end (about 20 minutes). Wait for
  it; do not kill it.
- The role and status colours in `ui/board.html` must equal the hall's.
