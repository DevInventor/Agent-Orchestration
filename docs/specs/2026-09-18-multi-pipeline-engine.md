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
| 14 | Working directory | **`<reposRoot>/wt-<slug>/<service>/`** — repos-root-shaped container, matching real GoTrust usage. Not `<repo>/.worktrees/`. |
| 15 | Shared knowledge base | **No file.** The codebase-memory graph *is* the shared knowledge; each pipeline keeps its own `index.md`. See §11. |
| 16 | Planner discovery | **Query the graph**, don't crawl. Dashboard indexes the registered repos. See §11. |
| 17 | Unit of work | **Workstream : run is 1 : N.** One branch and container outlive several runs. See §3.3. |
| 18 | Reviewer persistence | **Reviewer writes through `pipe.py`** (`Bash`, no `Write`/`Edit`). See ADR-0001. |
| 19 | Operational work | **An optional `operator` agent** runs things and reports evidence; the orchestrator assesses. See §12. |
| 20 | Agent preamble | **Role cheatsheets**, not the full protocol, for coder/tester/reviewer. See §13. |
| 21 | Dashboard design | **The hall mockup is the binding reference**, not an illustration. Tokens, motion, cast and layout are settled; build against them rather than re-deriving. See §10.0. |

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

<reposRoot>/wt-<slug>/                  the pipeline's working directory
├── <serviceA>/          git worktree of <reposRoot>/<serviceA>, branch feature/<slug>
├── <serviceB>/          git worktree of <reposRoot>/<serviceB>, same branch name
└── agent-orchestration.config.json     the root registry, trimmed to these services
```

**The working directory is repos-root-shaped, not repo-internal.** An earlier draft put
worktrees at `<repo>/.worktrees/<slug>/`. That is wrong for this topology and was corrected
against real usage (GoTrust, 2026-09-18): the repos root is **not itself a git repo** — it
is a plain container whose children are the service repos. A pipeline therefore needs a
container that *looks like* the repos root, so `reposRoot: "."` and every relative service
path resolve identically to the main checkout. Scattering one feature across three repos'
internal `.worktrees/` would break that and split one feature across three places.

`wt-<slug>/` is the layout arrived at by hand across 11 real features; the engine automates
it rather than replacing it. The trimmed config is generated from the root registry ∩ the
services `plan.json` names — no hand-editing.

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
      "worktree": "/abs/repos/wt-009-messaging-hub/OpenCRM",
      "branch": "feature/009-messaging-hub", "base": "develop" }
  ],
  "mode": "worktree | in-place"
}
```

`base` is recorded **at creation**, so each repo merges home to *its* own branch —
`develop` for one, `master` for another. Hardcoding `master` would break on the first real
microservice run.

### 3.1 One pipeline, one feature branch — decided up front

The branch name is derived at **`init`, before any work starts**, and announced at the
spec gate. You know `feature/<slug>` before the planner even runs, and nothing later can
change it. Only its *materialisation* (the worktree) waits for the finalize gate, because
that is when the services are known.

A pipeline spanning N repositories uses **the same branch name in every repository**. That
is what makes it one feature branch: one name, one identity, one merge unit. All of the
pipeline's work across every service lands on it, and `finish` merges that single name
home in each repo.

This holds in `in-place` mode too — the constraint is about the branch, not the worktree.
In-place runs `git switch -c feature/<slug>` in each touched repo, and **refuses to start if
a working tree is dirty** rather than mixing your uncommitted work into the feature.

### 3.2 Work must be committed, or there is nothing to merge

**This is a gap in the pipeline as it stands.** No agent commits anything today: the coder
ends at `git diff > pipeline/code/diff.patch` and the change sits uncommitted in the
working tree. With a feature branch as the merge unit that is no longer sufficient — an
uncommitted worktree merges as nothing, and `finish` would cheerfully merge an empty
branch.

- The **coder commits after each task completes**, and after each fix iteration, with the
  task id in the subject (`T3: shared session contract types`). Commits accumulate on
  `feature/<slug>`.
- **`diff.patch` changes meaning**: it becomes `git diff <base>...HEAD` — the cumulative
  feature diff. Plain `git diff` is **empty once the work is committed**, so leaving
  `agents/coder.md` as it is would hand the reviewer a blank diff. This edit is required,
  not optional.
- `finish` merges with `--no-ff` so the feature keeps its shape in history.
- The commit is the coder's last act on a task, after `task update --status done`. A task
  marked done with no commit is a defect the `finish` plan will surface as a zero-commit
  repo.

### 3.3 A workstream outlives its runs

**This corrects a 1:1 assumption in the first draft.** Observed usage: `wt-method23` is one
branch, `feature/method2-passkey-enrolment`, hosting **three** runs — Wave 1, an MFA
provisioning run, then Wave 2. `wt-stepup` and `wt-marketplace` host two each. Work arrives
in waves; the branch persists across them.

| term | lifetime | identified by |
|---|---|---|
| **Workstream** | one feature, start to merge | `slug` — names the branch, container and route |
| **Run** | one pass of spec → done over it | `runId` — a workstream has many |

Consequences the first draft got wrong:

- **`finish` closes a run, not the workstream.** Closing Wave 1 must not remove the
  worktrees Wave 2 stands on. Merging and tearing down the container is a separate,
  explicit act.
- **The branch is named once, when the workstream is created** — never per run. This
  removes the split-branch class of bug by construction: in `wt-stepup`, oauth's worktree
  was branched during run 1 and never re-branched for run 2, so a merge of run 2 takes
  three repos and silently leaves the fourth behind. Observed in 2 of 11 real containers.
- **The hall shows one row per workstream**, with its run history — not three unrelated
  rows for three waves of one feature.
- Each run still gets its own bus. Runs are the thing that archive; workstreams are the
  thing that merge.

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
   creates the bus at the fixed path and **fixes the branch name `feature/<slug>` now**.
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
   `feature/<slug>` from each repo's current HEAD, record `repos[]`. A **rejected plan leaves
   zero git residue.**
6. **Build** — coders/testers/reviewers work in the worktree, not the checkout. Per-service
   fix budget of 5 and dependency waves as today. **The coder commits each completed task
   to `feature/<slug>`** (§3.2); every service's commits land on that one branch name.
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
| `ls` | Lists pipelines by scanning the root: slug, feature, phase, status, repo count, age. Flags three drift states seen in real use: **stale** (`running`/`awaiting_approval` untouched > 3 days), **orphan** (a `wt-<slug>/` with no bus, or a bus with no worktrees), and **branch drift** (services in one pipeline on different branch names). |
| `prune` | `git worktree prune` across every registered repo, plus removal of `wt-<slug>/` containers whose pipeline is archived. Clears the detached-HEAD leftovers past sessions leave behind. |
| `gate --decision finalize\|in-place\|reject` | Writes `gate.json`. Releases the watcher. |
| `wait --for gate [--timeout N]` | Blocks until `gate.json` exists. Run via background Bash. |
| `worktree add --service <n> --repo <path>` | Creates the worktree, records `repos[]` incl. `base`. Verifies `.worktrees/` is git-ignored first. |
| `finish <slug>` | **Plan only.** Prints per repo: branch → base, commit count, dry-run verdict. Changes nothing. |
| `finish <slug> --apply` | Performs it, all-or-nothing (§8). |

## 8. `finish` semantics

Git has no atomic multi-repo merge, so `finish` builds one.

**Plan (default).** For each repo in `repos[]`, run `git merge-tree --write-tree <base>
feature/<slug>` — this tests the merge **without touching any working tree** (git ≥ 2.38;
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
record that the work happened. The bus is archived under **one** convention —
`pipelines/<slug>.closed-<YYYYmmdd>/` — replacing the four hand-rolled variants seen in
real use (`pipeline-closed-run-…`, `pipeline-closed-…`, `pipeline-archive-run-…`,
`pipeline-backup-run-…`).

## 9. Slug derivation

The slug names the bus directory, the branch `feature/<slug>`, the worktree directory, the
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

### 10.0 The design reference is binding

The hall mockup is **the design contract for this section**, not an illustration of it.
Everything from §10.1 to §10.6 is settled and was arrived at by iteration; an
implementation that re-derives the palette, the motion, or the sprite system has produced
a different product, not a faithful one.

| Artifact | Covers |
|---|---|
| `https://claude.ai/artifact/XX4ghERezYsbR3jxhzpM18` (v12) | The hall, the office floor, the cast, the motion inventory |
| `https://claude.ai/artifact/47YpPDBQA2phTN8Fjpp1Y1` | Flow and parallelism diagrams, the board, the repos tab |

**Binding:** tokens, layout, state-to-visual mapping, motion values, the cast and its
layer structure. **Not binding:** the example data, and the "review rig" buttons under the
mockup (Fire a handoff / Advance a phase / Let one go quiet / Reset) — those exist so
motion can be reviewed and are explicitly not part of the product.

**One correction to carry over.** The mockup's own office prose claims the office cast is
DiceBear's `pixel-art` set. It is not, any more — that set was tried and rejected on looks
and the original drawn cast was restored. The code is right (`who()` delegates to
`sprite()`); that one paragraph is stale. Build from the code, not that paragraph.

### 10.1 Tokens

Two themes, resolved three ways: bare `:root` is light, `@media (prefers-color-scheme:
dark)` guarded by `:root:not([data-theme="light"])` is system dark, and
`:root[data-theme="dark"]` lets an explicit toggle win in both directions.

| Token | Light | Dark |
|---|---|---|
| `--ink` / `--panel` / `--sunk` / `--raise` | `#F5F6F9` / `#FFFFFF` / `#ECEEF3` / `#FFFFFF` | `#090C12` / `#11151D` / `#0D1118` / `#171D28` |
| `--line` / `--line-2` | `#DCE0E7` / `#C2C9D4` | `#1D2531` / `#2C3644` |
| `--text` / `--bright` / `--muted` / `--faint` | `#3A424F` / `#0E131B` / `#6B7585` / `#98A1AF` | `#C7CEDA` / `#EDF1F6` / `#7A8496` / `#4A5464` |
| `--planner` / `--coder` / `--tester` / `--reviewer` / `--orch` | `#9A6B10` / `#1A6CA8` / `#A33468` / `#1B7A52` / `#6B4FA8` | `#F2C14E` / `#4FA6E0` / `#E06C9F` / `#5FCF9B` / `#A98BEA` |
| `--ok` / `--warn` / `--bad` | `#1B7A52` / `#9A6B10` / `#B03A34` | `#5FCF9B` / `#F2C14E` / `#E0655F` |
| `--felt` (table surface) | `#E7EAF0` | `#121822` |

Floor tokens, used only by the office view:

| Token | Light | Dark |
|---|---|---|
| `--floor` / `--floor-2` / `--grout` | `#DFE4EA` / `#D3D9E1` / `rgba(255,255,255,.7)` | `#161C26` / `#131922` / `rgba(255,255,255,.045)` |
| `--wall` / `--wall-edge` / `--wall-shadow` | `#FBFBFC` / `#C8CFD8` / `rgba(28,38,52,.14)` | `#232C3A` / `#0E131B` / `rgba(0,0,0,.6)` |
| `--wood` / `--wood-2` / `--deskglass` | `#B9C1CC` / `#98A3B2` / `#EEF1F5` | `#39465A` / `#2A3446` / `#2E394A` |
| `--chairc` / `--chairc-2` | `#7F8B9B` / `#68748453` | `#3A4658` / `#2C3644` |
| `--skin` / `--legs` / `--shoe` | `#D8A57C` / `#3C4A63` / `#2B3344` | `#C08E64` / `#2C3548` / `#1B2130` |
| `--eye` / `--pupil` | `#28313F` / `#11161F` | `#070A0F` / `#05080D` |
| `--screen` / `--screen-b` / `--pot` / `--leaf` | `#2F9E73` / `#E4E8EE` / `#9BA5B2` / `#7E97A8` | `#3FBE8B` / `#1E2733` / `#39465A` / `#46606F` |

**The palette is cool slate, and there is no brown anywhere.** This is load-bearing: the
first floor read as a school hall, the instinct was to blame the cast, and it was the
room. Warm wood and sage read playful whatever stands on them. On slate the same
characters read as an operations room.

Type: `--mono` is Fira Code, `--sans` is Fira Sans. Easings are
`--ease-out: cubic-bezier(0.23, 1, 0.32, 1)` and
`--ease-in-out: cubic-bezier(0.77, 0, 0.175, 1)`.

> **Implementation note, not a design change.** The mockup pulls Fira from Google Fonts
> with a `<link>`. `ui/server.js` is deliberately dependency-free and serves a local page,
> so the product must not *depend* on that request: declare the families with real system
> fallbacks (`ui-monospace, Menlo, Consolas, monospace` / `system-ui, -apple-system,
> "Segoe UI", sans-serif`) and let the page render correctly with no network. Self-hosting
> the woff2 files is the alternative; either is acceptable, blocking on a CDN is not.

### 10.2 The hall (`/`)

A segmented control switches **Hall** and **Office** — the same bus data, read two ways.
Hall is the working view (position means role); Office is the ambient one.

Left of the hall is the **head table**: the orchestrator with a one-line "what it is doing
now" in the same voice as a team's last event, exactly **three** counts (running /
awaiting you / quiet — a head table crowded with metrics competes with the hall it
summarises), and the **repository registry**. The registry belongs here because indexing a
repo is an orchestrator-level act shared by every team: each row shows index state and
node count (`fresh` / `drift` — HEAD moved / `none` — never indexed), there is a field to
add another, and a hand-off link to `localhost:9749/?tab=stats` (§11).

One card per pipeline, and the card is a table:

- **Header** — feature name, `open →` affordance on hover, and a status pill
  (`run` / `gate` / `done` / `stale`). Card border takes the same colour.
- **Repos line** — the services this workstream touches.
- **The surface** — the felt, with four seats at its corners in pipeline order clockwise:
  `planner` top-left, `coder` top-right, `tester` bottom-right, `reviewer` bottom-left.
- **The phase rail** — across the middle of the felt: `spec → plan → implement → test →
  review → done`, current tick scaled and pulsing in the active agent's colour.
- **The baton** — one token resting on the felt, inset 26 px from its seat's corner,
  recoloured to whoever holds the work. Consecutive hops therefore run along an edge: the
  path reads as passing work round a table, not cutting across it.
- **Foot** — phase, fix-loop position, test count (red when failing).
- **Stale strip** — `◉ no activity 6m — agent may have died`, on a run claiming `running`
  whose bus has not been written to for ~3 min (D3, shipped).
- **Last event**, one line.
- **Gate row** — `Finalize` / `In place` / `Reject`, on a waiting card only. These are
  §14's three fixed values and nothing else.

Footer count reads `N teams · N awaiting you · N quiet`.

### 10.3 The cast

Four people you can tell apart **without reading a colour**: the planner is an old man
(silver, receding at the temples), the coder a boy (dark fringe), QA a girl (long auburn),
the reviewer an uncle (moustache). An orchestrator sits apart at the head table.

- **Hair is a separate SVG layer over a shared body.** The shirt keeps the role colour via
  `currentColor` while the hair gives each agent a face, so the team reads two ways at
  once. Skin, legs, shoes and pupils come from theme tokens.
- **Two hair layers per character**, `hair-<role>` and `hair-<role>-back`. The front one
  caps the head and leaves room for a face; the back one fills the whole skull, because
  from behind there is no face to leave room for. `sprite()` appends `-back` automatically
  for rear-facing seats and never for `sleep`. **Skipping this is what made the near pair
  render as blank heads** — bare scalp with a fringe balanced on it. It was the last bug
  fixed in the mockup; do not reintroduce it.
- Hair colours: planner `#CFCBC2` / `#E2DFD8`, coder `#5B4636` / `#4A382B` / `#6B5544`,
  tester `#8A4B2F` / `#7A4129` / `#9A573A`, reviewer `#3A2E22` / `#4A3B2C`,
  orchestrator `#4A4258`.
- **Eyes need the dedicated near-black `--pupil` token** and roughly 3.6 px of rendered
  width (a 1.6–1.7 unit rect in the 12×18 viewBox at the 27 px render size). At the
  original ~1.8 px they vanished entirely under `shape-rendering: crispEdges`.
- Chibi proportions — head about 45% of the body — and `crispEdges` throughout.

### 10.4 Motion inventory

Eight entries, and six of them are one agent's states plus the two that mark a change.
**If this list grows to twenty, that is the bug.**

| What | Trigger | Property | Curve & duration |
|---|---|---|---|
| Baton travel | handoff | `transform` | 280 ms `ease-in-out` |
| Typing | agent holds the work | `transform` | 340 ms `steps(1)`, loops |
| Waiting | turn not yet come | `transform` | 3.4 s `steps(1)`, loops |
| Asleep | agent finished | `opacity`, `transform` | 3.6 s, loops |
| Walking in | baton lands | `transform` | 440 ms `steps(4)`, once |
| Table entrance | first paint only | `transform`, `opacity` | 260 ms `ease-out`, never replays |
| Repo row in | you register a repo | `transform`, `opacity` | 240 ms `ease-out` |
| Going quiet | run stale > 3 min | freeze + `opacity` | 2.6 s `ease-in-out`, loops |

Rules that come with it:

1. **Stepped, never eased.** Every sprite loop is `steps(1)` or `steps(4)`. A pixel
   character that tweens smoothly stops reading as a sprite and starts reading as a moving
   `div`. The snap is what makes it look drawn.
2. **Exactly one agent per table types.** The rest wait or sleep at much lower amplitude,
   so "busy" stays legible by being the exception in its own row.
3. **Something always moves at rest.** A completely still floor reads as a broken
   dashboard. This was overruled three times in favour of stillness and restored each
   time; it is settled.
4. **Stillness is the alarm.** A stale team freezes mid-keystroke and dims
   (`animation-play-state: paused`). In a hall where working things move, that reads
   instantly — which is also what makes D5 visible rather than silent.
5. **`transform` and `opacity` only.** No layout, no paint, so a full hall stays smooth
   while the page does other work. No `transition: all`, no `scale(0)`, no `ease-in`.
6. **`prefers-reduced-motion` stops every loop and leaves the resting pose** — eyes still
   shut on a sleeping agent, colours unchanged. The dashboard must say exactly the same
   thing with nothing moving.

### 10.5 The office floor

One open floor; the building's outer wall is the only wall. A team is a **desk island on a
rug, and the rug carries the state** — amber for a gate, red for a run gone quiet, faded
for one that is finished. You read the rug before you find a single agent, which is what a
floor plan must earn, being slower to scan than a table.

- **Seating is facing pairs** — desks back to back down the middle, bodies on the outer
  edges. Chosen explicitly over solo desk, round table and bench row, because it fits four
  in nearly the space of two and **no agent is ever in front of a screen**. The bottom pair
  is `back: true`. Offsets, per agent: planner `(26,4)` desk `(12,34)`, coder `(96,4)` desk
  `(82,34)`, tester `(26,120)` desk `(12,86)`, reviewer `(96,120)` desk `(82,86)`.
- **The working desk's screen scrolls.** The cheapest possible "something is happening
  here" that moves no body at all.
- **Walkers move on a corridor graph, one axis at a time.** Desk islands occupy x 18–174 /
  212–368 / 406–562 and y 16–134 / 168–286, so the walkable space is the two vertical
  aisles and the two horizontal ones. Every edge in `NODES` / `EDGES` is purely horizontal
  or vertical — that is what stops a walker cutting the corner through somebody's desk.
  The two walkers are the only thing in the room that means nothing, and they are grey for
  exactly that reason.
- **Zoom and pan over real DOM**, not a canvas rewrite: every agent keeps its tooltip, its
  CSS animation and its theme tokens. Ctrl+wheel zooms anchored on the pointer, drag pans,
  range 0.5–2.5.
- Behaviour maps to state, not decoration: typing at a desk = holds the work, asleep =
  finished, frozen mid-keystroke = quiet, team round the meeting table = a finalize gate.

### 10.6 Board (`/r/<slug>`)

Three panes: team comms left, task flow centre (six columns: To do → Coding → Ready for QA
→ QA → Review → Done, each headed in its owning agent's colour), completion matrix right.
Panes minimise to a labelled spine and the dividers drag; **the task flow absorbs the
slack**, so shrinking a side pane widens the board rather than opening a gap. If the task
flow itself is minimised, the first open pane takes that role. Widths persist across team
switches.

The matrix counts tasks that have **reached** a stage or passed it, not tasks sitting in
it — so the gap between adjacent columns is the work in flight at that stage, which is the
bottleneck you opened the dashboard to find. A row stopping short at QA is a service
drowning in test failures; one stopping at Rev is waiting on a reviewer. Fix budget sits
underneath, so one glance answers both "how far along" and "how much rope is left".

Sources: comms from `messages.jsonl` filtered by `runId`; flow from `tasks.json` plus
per-service results; the matrix derived — **no new state on the bus**.

### 10.7 Settled — do not re-open

Each of these cost a full session and has a reason behind it.

1. The cast is four **drawn** pixel characters, original work in this repo.
2. Hair is a separate layer, and there are **two** of them per character.
3. Seating is facing pairs.
4. The palette is cool slate. No brown.
5. Walkers use a corridor graph, one axis at a time.
6. Pupils use `--pupil` at ~3.6 px.
7. Something always moves at rest.

**Licensing, already checked.** `pixel-agents-hq/pixel-agents` states **no licence** — do
not copy from it. DiceBear `pixel-art` is CC0 1.0 and safe, but was tried and rejected on
looks. The current cast is original work here. Anthropic's logo is a *trademark* question
rather than a copyright one — using it implies endorsement, so it is avoided.

### 10.8 Still open — decide before building the hall, not during

- **Is a full room too busy?** Five teams read well in both views. At twelve the office
  floor runs out of room before the hall does; the lever is scrolling the floor, or keeping
  loops only on what is in view.
- **Should agents walk between desks on a handoff?** They hold position today and only a
  gate gathers them. Walking would be charming, but a character in transit is a character
  whose state you cannot read.
- **Should a finished team leave the hall?** `done` teams stay, dimmed. They could collapse
  to a row so the hall holds only live work — at the cost of the day's history at a glance.
- **The operator (§12) has no seat.** It is the one role that is not always present, so
  the four-corner layout has nowhere to put it. Needs an answer as part of AC9.

## 11. Codebase knowledge: the graph, not a file

**A shared `knowledge-base.md` was designed and then rejected**, on evidence from the
GoTrust repos-root. Recording why, so it is not proposed again.

That project already keeps five overlapping knowledge stores: a hand-written
`Docs/AI-Agent-Quick-Context.md`, `.claude/memory/`, a MemPalace config, 19 per-pipeline
`index.md` files, and a codebase-memory graph. The hand-written one is **five months
stale** and its "Fast Commands for Next Agent" instruct the agent to `cd D:/Tenup/GoTrust/…`
— a drive that does not exist. A generated sixth file would have been one more artifact
that drifts out of step with the code.

**The graph is already the shared knowledge and nothing was using it.** That project's
index is `ready` at **89,192 nodes / 304,535 edges**, while every planner still crawled
with Glob/Grep. Two of the 19 indexes (`codebase/docker/pipeline/index.md` and
`wt-stepup/pipeline/index.md`) are **byte-identical** — the same 26 KB crawl paid for
twice — and the 19 together are ~55,600 tokens of *output*, with the reading behind them
many times larger.

### What this means for the pipeline

- **Each pipeline keeps its own `index.md`.** It stays the per-run shared context the
  coder and tester read. What changes is how it is produced.
- **The planner queries instead of crawling.** `get_architecture` for orientation,
  `search_graph` to locate the feature's symbols, `trace_path` for callers and callees,
  `get_code_snippet` for exact source. `index.md` becomes a short description of *what
  this feature touches*, not a re-description of the codebase.
- **The dashboard indexes the project's repos.** The service registry already names them;
  an *Index repos* action runs `index_repository` over that set and reports node counts
  and coverage per repo. Indexing once serves every pipeline on those repos.
- **No new file, no new staleness model.** Freshness is the graph's own concern —
  `index_status` and `detect_changes` already report it, and watched projects refresh in
  the background.

### Downstream quality, not just tokens

The same queries improve the work rather than only cheapening it: `trace_path(inbound)`
gives the tester the real caller set instead of a guess at which dataflows matter, and
`detect_changes()` gives the reviewer a precise blast radius instead of the whole diff.

## 12. The operator, and who assesses

Measured across 22 buses, **16% of orchestrator events are it doing the work itself** —
*"DEPLOYED to AWS: sso 3e15f07"*, *"REBUILD DONE (autonomous): oauth image…"*,
*"JANUS CANNOT START — startup requires a live mTLS Vault"*. Its event `detail` payload
(93,847 bytes) essentially ties the coder's (94,168).

This is a **missing role**, not indiscipline. No agent owns deploying, rebuilding,
restarting or diagnosing an environment, so it falls to the orchestrator by default — in
the longest-lived, most expensive context in the run, where the logs it reads stay resident
for everything that follows. It also makes the orchestrator player and referee: it ran the
QA gate on work it had performed.

**The operator does; the orchestrator assesses.**

- The **operator** runs the thing and absorbs the logs, retries and noise in its own
  disposable context. It reports through `pipe.py` in a fixed shape — command, exit code,
  what changed, what to verify — and is **forbidden from concluding success**. It reports
  evidence, never a verdict. It never writes feature code.
- The **orchestrator** reads that compact report and makes the call, so the judgement stays
  visible in the run's narrative rather than buried in a subagent's scrollback.
- It is **optional**: spawned only when the plan names an operational task. Most runs never
  use it, so projects that never deploy are unaffected.

**Anything touching a shared environment waits at a gate.** Deployment is outward-facing
and hard to reverse, and everywhere else in this design an irreversible step is gated — the
plan is, `finish --apply` is. Deployment is not the exception. The operator may diagnose and
rebuild freely; pushing to a shared stack uses the same `gate.json` mechanism as the
finalize gate. Assess, then deploy — not deploy, then assess.

## 13. The spawn preamble is the largest token line item

Every agent spawn reads `team-rules.md`, the full `pipeline-protocol` skill, and its own
definition before doing anything:

| document | bytes | who needs all of it |
|---|---|---|
| `pipeline-protocol/SKILL.md` | 7,662 | the orchestrator |
| `agents/team-rules.md` | 2,248 | everyone |
| the agent's own file | 2,310–4,693 | itself |

A 3-service run with one fix round is **19 spawns ≈ 58,000 tokens of preamble before any
work**, and **62% of that (~36,400 tokens) is the protocol document alone**. It carries the
multi-service namespace rules, the `run.json` schema, the full 12-command CLI and the
config-registry contract. **A coder uses four commands.**

**Each role's agent file carries its own ~400-byte command cheatsheet**; only the
orchestrator reads the full protocol, which stays in the repo as the reference an agent
*may* consult for anything unusual.

The obvious risk is drift between the cheatsheets and `pipe.py`, and it is closed
mechanically rather than by discipline: `test_pipe.py` asserts that **every command named in
any agent file exists in `pipe.py`'s parser**. Duplication is dangerous when nothing catches
it; this catches it.

## 14. Security boundary

`POST /api/gate` is the first path where a browser can trigger git operations.

- Bind to **`127.0.0.1` only**.
- The endpoint accepts one of three fixed values (`finalize`, `in-place`, `reject`) — no
  free-form input, no path parameters, no slug traversal (resolve the slug against the
  scan list, never against the filesystem directly).
- The gate can only *release a waiter*. It never triggers `finish --apply`; merging stays
  an explicit command.

## 15. Out of scope

- **Cross-session juggling** — one session driving multiple pipelines. Deferred by
  decision; it would require abandoning the blocking finalize gate.
- **PR creation** — `--pr` swapping `git merge` for `gh pr create` on the same
  all-or-nothing check, once wanted. `gh` 2.97 is present.
- **Spec write-back and doc relocation** — declined.
- **Per-service detail on the hall** — the board is one click away.

## 16. Backward compatibility

- `pipe.py --root` keeps working; an existing `./pipeline` bus is still readable.
- `server.js --pipeline <dir>` keeps working for a single bus.
- `in-place` mode is today's behaviour exactly, reachable from the finalize gate.
- Legacy `messages.jsonl` without `runId` already falls back to the raw tail (shipped, D4).

## 17. Risks

| Risk | Handling |
|---|---|
| `.worktrees/` not git-ignored → worktree contents committed | `worktree add` verifies with `git check-ignore` and adds the entry before creating anything. |
| Two pipelines touch the same files in one repo | Not preventable, and not silent: caught by `finish`'s dry run with the conflicting files named. |
| A stale pipeline directory outlives its repo | `finish` cleans on success; `ls` flags a pipeline whose repo paths no longer exist. |
| Background watcher dies, gate never releases | The gate file is durable — re-arming the watcher picks up an approval that already landed. |
| Coder marks a task done without committing | The `finish` plan reports that repo's commit count as 0 before anything merges, so an empty feature cannot ship unnoticed. |
| Dirty working tree when starting `in-place` | Refused up front; the run never mixes pre-existing uncommitted work into the feature branch. |
| Services in one pipeline drift onto different branch names | Observed in **2 of 11** real containers, where `finish` would have merged 3 repos and silently missed the 4th. The branch name is fixed at `init`, `worktree add` uses only that name, and `ls` reports drift on pre-existing containers. |
| A worktree container outlives its bus, or vice versa | Observed twice (`wt-mfa-authority`, `wt-phase2-a2`). `repos[]` binds them in one record and `ls` reports either half missing. |
| Slug collision across projects | Collision is checked against *active* pipelines and suffixed; `repos[]` stores absolute paths so repos stay unambiguous. |

## 18. Files this touches

| File | Change |
|---|---|
| `scripts/pipe.py` | `init --slug`, `ls`, `gate`, `wait`, `worktree add`, `finish` (+`--apply`) |
| `agents/coder.md` | **commit each completed task**; `diff.patch` becomes `git diff <base>...HEAD` (§3.2) |
| `docs/orchestration-runbook.md` | spec gate; branch announced at init; worktree creation at finalize; `finish` at QA |
| `skills/ship`, `skills/ship-from-spec` | slug derivation, `--root` baked into `$PIPE` |
| `skills/pipeline-protocol` | `repos[]`, `gate.json`, per-pipeline root |
| `ui/server.js` | scan mode, `/`, `/r/<slug>`, `/events?run=`, `POST /api/gate` |
| `ui/index.html` | hall overview, office floor, board panes, gate buttons, **Index repos** action — built to §10's design contract. Sprites are inline SVG `<symbol>`s, so no new asset files and no runtime fetch. |
| `agents/planner.md` | **query the graph instead of Glob/Grep crawling**; `index.md` becomes a feature delta (§11) |
| `agents/tester.md` | `trace_path(inbound)` for the real caller set (§11) |
| `agents/reviewer.md` | `detect_changes()` for the blast radius (§11); **persists via `pipe.py`, gains `Bash`, keeps no `Write`/`Edit`** (ADR-0001) |
| `agents/operator.md` | **new** — runs things, reports evidence, never concludes (§12) |
| `agents/*.md` | each gains a ~400 B command cheatsheet; the full protocol stops being mandatory (§13) |
| `CONTEXT.md` | **new** — the glossary these agents read |
| `docs/adr/0001-…` | **new** — why the reviewer writes through `pipe.py` |
| `scripts/test_pipe.py` | slug rule, `finish` plan/apply, gate round-trip, **agent-cheatsheet drift check** (§13) |

## 19. Related tracked work

From `pending-task.md`: **P1** (server-side fix-loop budget) should land before or with
this — the multi-service escalation logic depends on a counter the engine can trust.
**D5** (unenforced emission) is largely absorbed by D3. **D1/D3/D4** shipped in `55f095b`.
