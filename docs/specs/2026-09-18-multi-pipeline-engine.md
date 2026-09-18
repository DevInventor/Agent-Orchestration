# Multi-pipeline engine — design

**Status:** approved for planning · **Date:** 2026-09-18 · **Supersedes:** nothing

Run several `/ship` agent teams at once, each on its own feature, isolated in git
worktrees, visible from one portal, and mergeable across repositories in one safe step.

---

## 1. Why

Today one run owns one `./pipeline` directory and works directly in your checkouts.
That is fine for one feature and **incorrect** for two.

Two teams sharing a checkout share a working tree, so the coder's
`git diff > diff.patch` — the artifact the reviewer judges — captures *both* features.
The reviewer then reviews work it was never given a plan for, and the tester runs against
a tree it did not expect. Isolation is not ergonomics here; it is what makes the
pipeline's existing artifacts true under concurrency.

Git already provides the isolation. The engine's job is narrower: make standing up a team
cheap, make every running team visible in one place, and make the end-of-feature merge
safe across several repositories at once.

This also closes **D2** from `pending-task.md` (one bus per repo, server binds one path).

## 2. Decisions

Each was put to the user and answered. Recorded so the implementation does not relitigate
them.

| # | Decision | Chosen |
|---|---|---|
| 1 | Unit of parallelism | **One Claude session per pipeline.** The engine is a registry + portal + merge layer; the orchestrator contract is unchanged. |
| 2 | What "git-trackable" means | **Code on branches.** The bus stays disposable run state, never committed. |
| 3 | When worktrees are created | **At the finalize gate** — the first moment `plan.json` names the services. |
| 4 | Watching N pipelines | **One server, one port.** Overview at `/`, existing dashboard at `/r/<id>`. |
| 5 | Merging at the end | **All-or-nothing**, `merge-tree` dry run across every repo first. |
| 6 | Where the registry lives | **`~/.agent-orchestration/pipelines/<id>/`** — fixed, machine-wide. Must serve multi-repo microservices as the primary case. |
| 7 | Does `/ship` change | **Auto-detect and ask.** Never silently switch behaviour on invisible state. |
| 8 | When it asks | **At the finalize gate**, where the service count is known and you already stop. |
| 9 | Spec-confirmation gate | **In the shared runbook precondition**, so both entry skills get it. |
| 10 | Approving from the browser | **Yes.** Mechanism in §6. |
| 11 | `finish` safety model | **Two-step plan / apply.** |
| 12 | Slug derivation | **Smart path rule** (§9). |
| 13 | Branch model | **One pipeline, one feature branch**, named at `init` before any work starts; same name in every repo. Agents must commit (§3.1–3.2). |

`/ship-from-spec` is the daily driver (`/grill-me` → spec doc → `/ship-from-spec`).
`/ship` is the occasional path. Where the two differ, optimise for `ship-from-spec`.

## 3. Layout

A pipeline owns **N repositories**. Microservices in separate repos is the primary case,
not an afterthought — which is precisely why the registry is not project-local: separate
repos have no natural shared root to put state in.

```
~/.agent-orchestration/pipelines/<slug>/
├── pipeline/            the bus — run.json, plan.json, tasks.json, messages.jsonl,
│                        spec.md, index.md, code/, test/, review/, status/, services/
└── gate.json            written by terminal OR browser; releases the waiter

<each-repo>/.worktrees/<slug>/     one per service the plan named, branch feat/<slug>
```

**There is no registry file.** The directory *is* the registry: `server.js` scans
`pipelines/*/pipeline/run.json`. Nothing to corrupt, nothing to keep in sync, self-healing
when a directory is deleted. Adding a team is creating a directory — no registration, no
config, no restart.

### run.json additions

```json
{
  "runId": "run-20260918-133922-860f",
  "slug": "009-messaging-hub",
  "repos": [
    { "service": "api",  "repo": "/abs/OpenCRM",
      "worktree": "/abs/OpenCRM/.worktrees/009-messaging-hub",
      "branch": "feat/009-messaging-hub", "base": "develop" }
  ],
  "mode": "worktree | in-place"
}
```

`base` is recorded **at creation**, so each repo merges home to *its* own branch —
`develop` for one, `master` for another. Hardcoding `master` would break on the first real
microservice run.

### 3.1 One pipeline, one feature branch — decided up front

The branch name is derived at **`init`, before any work starts**, and announced at the
spec gate. You know `feat/<slug>` before the planner even runs, and nothing later can
change it. Only its *materialisation* (the worktree) waits for the finalize gate, because
that is when the services are known.

A pipeline spanning N repositories uses **the same branch name in every repository**. That
is what makes it one feature branch: one name, one identity, one merge unit. All of the
pipeline's work across every service lands on it, and `finish` merges that single name
home in each repo.

This holds in `in-place` mode too — the constraint is about the branch, not the worktree.
In-place runs `git switch -c feat/<slug>` in each touched repo, and **refuses to start if
a working tree is dirty** rather than mixing your uncommitted work into the feature.

### 3.2 Work must be committed, or there is nothing to merge

**This is a gap in the pipeline as it stands.** No agent commits anything today: the coder
ends at `git diff > pipeline/code/diff.patch` and the change sits uncommitted in the
working tree. With a feature branch as the merge unit that is no longer sufficient — an
uncommitted worktree merges as nothing, and `finish` would cheerfully merge an empty
branch.

- The **coder commits after each task completes**, and after each fix iteration, with the
  task id in the subject (`T3: shared session contract types`). Commits accumulate on
  `feat/<slug>`.
- **`diff.patch` changes meaning**: it becomes `git diff <base>...HEAD` — the cumulative
  feature diff. Plain `git diff` is **empty once the work is committed**, so leaving
  `agents/coder.md` as it is would hand the reviewer a blank diff. This edit is required,
  not optional.
- `finish` merges with `--no-ff` so the feature keeps its shape in history.
- The commit is the coder's last act on a task, after `task update --status done`. A task
  marked done with no commit is a defect the `finish` plan will surface as a zero-commit
  repo.

## 4. Concurrency model

One writer per file, fan-in by filesystem. No broker, no queue.

Each team writes **only** inside its own `pipelines/<slug>/` directory and never touches
another's, so there is no cross-team coordination problem to solve. The server scans the
parent and merges for display. `run.json` is a team's public status; `messages.jsonl` is
its narrative. Within a team, `pipe.py`'s existing lock already guards `run.json` and
`tasks.json` against concurrent same-batch subagents; `messages.jsonl` is append-only and
safe without one.

## 5. Lifecycle

1. **`/ship-from-spec <doc>`** — read the doc, derive the slug (§9), `pipe.py init --slug`
   creates the bus at the fixed path and **fixes the branch name `feat/<slug>` now**.
   Dashboard is started (already shipped, D1).
2. **Spec gate** *(new — runbook precondition, both entry skills)* — show the acceptance
   criteria that were read or distilled **and the branch this pipeline will use**, then
   wait for OK. With `/grill-me` upstream this is
   usually one keystroke, but it catches a misreading *before* a full planning pass is
   spent on it.
3. **Plan** — the planner indexes the **real checkouts**, read-only (its tools are
   `Read, Grep, Glob, Bash` — no Edit/Write). Always current state, never a stale snapshot.
4. **Finalize gate** — present the plan plus the detection line:
   > *3 services: OpenCRM, SpiceTrade, Deployment. 2 other pipelines active.
   > `finalize` for isolated worktrees, or `finalize in-place` to work in your checkouts.*

   Arm the watcher (§6), then end the turn. A service directory that is not a git repo is
   reported and forced in-place.
5. **On finalize** — create one worktree per service named in `plan.json`, branch
   `feat/<slug>` from each repo's current HEAD, record `repos[]`. A **rejected plan leaves
   zero git residue.**
6. **Build** — coders/testers/reviewers work in the worktree, not the checkout. Per-service
   fix budget of 5 and dependency waves as today. **The coder commits each completed task
   to `feat/<slug>`** (§3.2); every service's commits land on that one branch name.
7. **`pipe.py finish <slug>`** — §8.

## 6. The gate mechanism

At the finalize gate the orchestrator **ends its turn** — nothing is running in that
session to receive a browser click. The mechanism that resolves this:

`Bash(run_in_background)` keeps running across turns and **re-invokes the session when its
command exits**. So:

1. Orchestrator presents the plan.
2. Arms a background watcher: `until [ -f gate.json ]; do sleep 2; done`.
3. Ends its turn. **The terminal stays free** — you can start another pipeline.
4. You approve from the terminal *or* the browser. `server.js` `POST /api/gate` writes
   `gate.json`; typing `finalize` writes the **same file** via `pipe.py gate`.
5. The watcher exits → the session wakes → worktrees are created, coders spawn.

Two front ends, one mechanism, no second code path that could disagree about what
"approved" means.

**An interactive prompt is not an option anywhere in this design.** `pipe.py` is invoked
by agents through a non-interactive shell; `input()` hits EOF. Every confirmation is either
a flag or a file.

## 7. `pipe.py` additions

| Command | Behaviour |
|---|---|
| `init --slug <s>` | Creates the bus under the fixed root. Existing `--root` still wins, so single-repo in-place runs are unaffected. |
| `ls` | Lists pipelines by scanning the root: slug, feature, phase, status, repo count, age. |
| `gate --decision finalize\|in-place\|reject` | Writes `gate.json`. Releases the watcher. |
| `wait --for gate [--timeout N]` | Blocks until `gate.json` exists. Run via background Bash. |
| `worktree add --service <n> --repo <path>` | Creates the worktree, records `repos[]` incl. `base`. Verifies `.worktrees/` is git-ignored first. |
| `finish <slug>` | **Plan only.** Prints per repo: branch → base, commit count, dry-run verdict. Changes nothing. |
| `finish <slug> --apply` | Performs it, all-or-nothing (§8). |

## 8. `finish` semantics

Git has no atomic multi-repo merge, so `finish` builds one.

**Plan (default).** For each repo in `repos[]`, run `git merge-tree --write-tree <base>
feat/<slug>` — this tests the merge **without touching any working tree** (git ≥ 2.38;
verified on 2.55). Print every repo with its verdict, commit count, and target base.
Change nothing. **A repo showing zero commits is a red flag, not a no-op** — it means the
coder never committed, and the plan says so rather than merging nothing silently.

**Apply (`--apply`).** Re-run every dry run. If **all** are clean: merge each into its
recorded base, remove the worktrees, archive the bus. If **any** conflicts: merge
**nothing**, name the repo and the conflicting files, exit non-zero.

Merging until something breaks would leave a feature half-shipped across services — the
worst state to debug. The re-run before applying is deliberate: the plan may be minutes
old and the bases may have moved.

**Worktrees are removed; branches are kept.** Worktrees regenerate; branches are the only
record that the work happened.

## 9. Slug derivation

The slug names the bus directory, the branch `feat/<slug>`, the worktree directory, the
hall row and the `/r/<slug>` route. It must be predictable enough to guess the branch name
without looking it up.

**Rule.** From the spec doc path:
1. Take the basename without extension.
2. If it is generic (`design`, `spec`, `README`, `index`, `requirements`, `plan`), use the
   **parent directory name** instead.
3. Strip a leading ISO date (`2026-07-27-`) and a trailing `-design` / `-spec`.
4. Slugify; cap at 40 chars.
5. If it collides with an **active** pipeline, append `-2`. Never silently reuse.
6. Show it at the spec gate — one word overrides it.

For `/ship` (no doc), fall back to slugifying the feature title.

**Verified against every spec path these buses have ever loaded — 7 of 7:**

| real path | slug |
|---|---|
| `crm/docs/superpowers/specs/2026-07-14-calculator-improvements-design.md` | `calculator-improvements` |
| `crm/specs/008-broadcast-groups/design.md` | `008-broadcast-groups` |
| `crm/specs/009-messaging-hub/design.md` | `009-messaging-hub` |
| `crm/specs/010-portfolio-review/design.md` | `010-portfolio-review` |
| `docs/ipo-mandate-automation-spec.md` | `ipo-mandate-automation` |
| `docs/superpowers/specs/2026-07-27-client-investment-horizon.md` | `client-investment-horizon` |
| `docs/superpowers/specs/2026-07-27-google-contacts-sync-design.md` | `google-contacts-sync` |

A plain basename rule yields `design` for 3 of these; a plain parent rule yields
`specs`/`docs` for 4. Both rejected on that evidence.

## 10. Server and UI

**`server.js`** — scan mode over the fixed root; `/` serves the hall; `/r/<slug>` serves
the existing dashboard; `/events?run=<slug>` scopes the SSE stream; `POST /api/gate`
accepts a decision. Existing `--pipeline` single-bus mode is retained so nothing breaks.

**Hall (`/`)** — one row per pipeline: feature, four agent seats lit by state, repos,
phase, fix-loop position, tests. Amber means a gate is waiting on you. Gate buttons appear
only on a waiting row. Staleness (shipped, D3) applies per row.

**Board (`/r/<slug>`)** — three panes: team comms left, task flow centre (six columns:
To do → Coding → Ready for QA → QA → Review → Done, each headed in its owning agent's
colour), completion matrix right. Panes are collapsible and the dividers drag; the task
flow absorbs slack so the layout never leaves dead space.

The matrix counts tasks that have **reached** a stage or passed it, not tasks sitting in
it — so the gap between adjacent columns is the work in flight at that stage, which is the
bottleneck you opened the dashboard to find.

Mockups: published artifact, `https://claude.ai/artifact/47YpPDBQA2phTN8Fjpp1Y1`.

## 11. Security boundary

`POST /api/gate` is the first path where a browser can trigger git operations.

- Bind to **`127.0.0.1` only**.
- The endpoint accepts one of three fixed values (`finalize`, `in-place`, `reject`) — no
  free-form input, no path parameters, no slug traversal (resolve the slug against the
  scan list, never against the filesystem directly).
- The gate can only *release a waiter*. It never triggers `finish --apply`; merging stays
  an explicit command.

## 12. Out of scope

- **Cross-session juggling** — one session driving multiple pipelines. Deferred by
  decision; it would require abandoning the blocking finalize gate.
- **PR creation** — `--pr` swapping `git merge` for `gh pr create` on the same
  all-or-nothing check, once wanted. `gh` 2.97 is present.
- **Spec write-back and doc relocation** — declined.
- **Per-service detail on the hall** — the board is one click away.

## 13. Backward compatibility

- `pipe.py --root` keeps working; an existing `./pipeline` bus is still readable.
- `server.js --pipeline <dir>` keeps working for a single bus.
- `in-place` mode is today's behaviour exactly, reachable from the finalize gate.
- Legacy `messages.jsonl` without `runId` already falls back to the raw tail (shipped, D4).

## 14. Risks

| Risk | Handling |
|---|---|
| `.worktrees/` not git-ignored → worktree contents committed | `worktree add` verifies with `git check-ignore` and adds the entry before creating anything. |
| Two pipelines touch the same files in one repo | Not preventable, and not silent: caught by `finish`'s dry run with the conflicting files named. |
| A stale pipeline directory outlives its repo | `finish` cleans on success; `ls` flags a pipeline whose repo paths no longer exist. |
| Background watcher dies, gate never releases | The gate file is durable — re-arming the watcher picks up an approval that already landed. |
| Coder marks a task done without committing | The `finish` plan reports that repo's commit count as 0 before anything merges, so an empty feature cannot ship unnoticed. |
| Dirty working tree when starting `in-place` | Refused up front; the run never mixes pre-existing uncommitted work into the feature branch. |
| Slug collision across projects | Collision is checked against *active* pipelines and suffixed; `repos[]` stores absolute paths so repos stay unambiguous. |

## 15. Files this touches

| File | Change |
|---|---|
| `scripts/pipe.py` | `init --slug`, `ls`, `gate`, `wait`, `worktree add`, `finish` (+`--apply`) |
| `agents/coder.md` | **commit each completed task**; `diff.patch` becomes `git diff <base>...HEAD` (§3.2) |
| `docs/orchestration-runbook.md` | spec gate; branch announced at init; worktree creation at finalize; `finish` at QA |
| `skills/ship`, `skills/ship-from-spec` | slug derivation, `--root` baked into `$PIPE` |
| `skills/pipeline-protocol` | `repos[]`, `gate.json`, per-pipeline root |
| `ui/server.js` | scan mode, `/`, `/r/<slug>`, `/events?run=`, `POST /api/gate` |
| `ui/index.html` | hall overview, board panes, gate buttons |
| `scripts/test_pipe.py` | slug rule, `finish` plan/apply, gate round-trip |

## 16. Related tracked work

From `pending-task.md`: **P1** (server-side fix-loop budget) should land before or with
this — the multi-service escalation logic depends on a counter the engine can trust.
**D5** (unenforced emission) is largely absorbed by D3. **D1/D3/D4** shipped in `55f095b`.
