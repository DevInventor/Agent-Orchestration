# Pending tasks

Deferred improvements. Current pipeline works; these are hardening, not blockers.

## P1 — Fix-loop budget is advisory, not enforced
`run.services[<svc>].loop.count` is a number the orchestrator writes and then trusts
itself to compare against `loop.max`. Nothing in code stops a miscount from looping
past 5. **Fix:** `pipe.py svc --bump-loop` increments server-side and returns
`{"blocked": true}` once it crosses `max`; orchestrator reacts to the flag instead of
doing its own arithmetic. Moves the guardrail from prose into code.
Files: `scripts/pipe.py` (`cmd_svc`), `docs/orchestration-runbook.md` (§M step 3).

## P2 — `pipe.py` has zero tests
The lock, `cmd_config`'s validator, and `cmd_task update` are all untested. For a tool
whose job is enforcing correctness on other agents, that is the wrong ordering.
**Fix:** one `scripts/test_pipe.py`, assert-based, no framework. Cover: config
validation rejects (bad JSON / dup name / missing path / unknown dep), task
add+update round-trip, lock mutual exclusion, `init` never walks up.

## P3 — `progressPct` is dead state
`recompute_progress()` (`scripts/pipe.py`) promises "phase completion + partial credit
for the coder/test loop" but only implements phase completion — and the dashboard
ignores the field entirely, recomputing its own in `computeProgress()`
(`ui/index.html`). **Fix:** delete one of the two. Prefer deleting the Python side and
letting the UI own presentation; drop `pipe.py progress` with it.

## P4 — Finalize gate is LLM judgment
The runbook asks the orchestrator to "sanity-check that plan.json has tasks +
acceptance criteria + a services list". **Fix:** `pipe.py validate-plan` exits non-zero
with a concrete message, making the gate deterministic.

---

# Dashboard visibility defects (found 18 Sep 2026)

Diagnosed from two real buses: `OpenCRM/pipeline` (475 events, 30 runs) and
`SpiceTrade/spice-trade-guardian-ui/pipeline` (12 events, 1 run). The bus itself is
healthy — agents write it correctly. Every defect below is on the *read* side.

## D1 — Nothing ever starts the dashboard  [DONE 18 Sep 2026]
`docs/orchestration-runbook.md` says "Tell the user the dashboard command once". That is
the only thing that ever mentions starting it. No agent, no skill, and no `pipe.py`
command launches `ui/server.js`. Confirmed: nothing was listening on 4600 during or after
either run. The server is a passive file reader — if it is not running there is no
dashboard, and nothing in the pipeline notices.
**Fix:** entry skill launches `node ${CLAUDE_PLUGIN_ROOT}/ui/server.js` via a background
Bash call at `init`, and prints the URL. Idempotent — skip if the port is already bound.

## D2 — One bus per repo, server binds exactly one path  [OPEN — the worktree engine]
`server.js` resolves `PIPELINE` once from `--pipeline` / `$PIPELINE_DIR` / `cwd`
(`ui/server.js`). `/ship` run inside two repos produces two buses. Whichever the server
is pointed at, the other is invisible; started at the repos root, neither is at
`./pipeline` and it shows "waiting for a run…" while a run is underway one level down.
**Fix:** the engine's fixed pipeline root + scan (see design). Interim: `pipe.py init`
records the absolute bus path in `~/.agent-orchestration/active.json` for the server to
resolve.

## D3 — A dead agent is indistinguishable from a working one  [DONE 18 Sep 2026]
`run.json` already carries `updatedAt` (written by `save_run` on every mutation) and the
UI **never reads it** — `ui/index.html` uses `startedAt` only, for an elapsed clock that
keeps ticking after everything has stopped. There is no heartbeat in `pipe.py`.
Evidence: SpiceTrade's own log records `orchestrator error — "Coder subagent died
silently after T1 (no notification); T2-T8 never started"`, logged **5h45m** after the
last coder event. For that whole window the dashboard would have read "coder ·
implement" with a rising timer.
**Fix:** UI reads `updatedAt`; over ~3 min with `status: running`, mark the run stale
(desaturate the lane, show "no activity 6m"). Data already exists — this is a read-side
change only. Cheapest high-value fix on the list.

## D4 — `messages.jsonl` is never scoped to a run  [DONE 18 Sep 2026]
Events carry only `{ts, agent, type, phase, summary}` — **no `runId`**. `init` resets
`run.json` but appends to the same log forever: OpenCRM's holds **30 runs** spanning
11 Jul – 12 Aug. `tailMessages(400)` (`ui/server.js`) therefore can render events from a
previous feature as part of the current one, and makes "idle between runs" look identical
to "stalled mid-run".
**Fix:** stamp `runId` into every event in `_event()`; server filters to the active
`runId`. Keeps one append-only file, makes the feed correct.

## D5 — Event emission is unenforced  [OPEN]
Protocol rule 1 says emit at every meaningful step; it is prose only. Same coder agent
emitted 182 events in one run and 1 in another. A silent agent produces an empty
dashboard that looks like a stalled one.
**Fix:** falls out of D3 — once staleness is visible, a non-emitting agent is *visible*
as stale rather than silently indistinguishable from progress.

---

# GoTrust review findings (18 Sep 2026)

Reviewed 21 buses / 11 worktree containers / 7 service repos at
`C:/Projects/Tenup/GoTrust`. Layout and branch corrections went into
`docs/specs/2026-09-18-multi-pipeline-engine.md`. These are the operational leftovers.

## G1 — Six of twelve stalled pipelines were simply never closed  [OPEN]
Not failures. `wt-vaultcred` (21/21 scenarios passed), `wt-rolecat` (412 unit + 219 IT,
0 failures), `oauth_v3.8.0/pipeline-superadmin-ui` (14/14, already deployed to AWS) and
`wt-marketplace/pipeline-archive-run-…` (20/20, deployed) are all green and still read
`status: running`. Two more sit at `awaiting_approval` for 16 and **25** days
(`pipeline-materialiser-phase-a`, `pipeline-connector-chain` — the latter 24/27 tasks).
`finish` plus the hall's stale flag is the fix; until then they need closing by hand.

## G2 — Duplicate bus snapshots  [OPEN]
`docker/pipeline-backup-run-20260902-115306-20260904-171240` and `…-20260907-171122` are
byte-identical (126 events each). One can be deleted. `finish`'s single archive convention
prevents the class.

## G3 — Planner crawls a graph that is already built  [OPEN → spec §11]
The codebase-memory index for that root is `ready` at 89,192 nodes / 304,535 edges, and
every planner still crawls with Glob/Grep. The 19 `index.md` files total ~55,600 tokens of
output, and `codebase/docker/pipeline/index.md` and `wt-stepup/pipeline/index.md` are
byte-identical — the same 26 KB crawl paid for twice. Specced in §11: query the graph,
keep a per-pipeline `index.md` as a feature delta.

## G4 — A hand-written knowledge base rotted  [WONTFIX — informs §11]
`Docs/AI-Agent-Quick-Context.md` is five months stale and its "Fast Commands for Next
Agent" tell the agent to `cd D:/Tenup/GoTrust/…`, a drive that does not exist. A shared
generated `knowledge-base.md` was designed and then **rejected** on this evidence: it would
be a sixth store to drift. The graph is the shared knowledge; each pipeline keeps its own
`index.md`.

## G5 — Orphaned worktrees from past sessions  [OPEN → spec, `pipe.py prune`]
Detached-HEAD worktrees left under the temp scratchpad (`vault-baseline`, `oauth-baseline`)
still registered in `GTID-Vault` and `oauth_v3.8.0`. `git worktree prune` fodder.
