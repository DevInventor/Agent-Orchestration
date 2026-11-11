# Agent-Orchestration

A feature-shipping pipeline in which a team of four specialist agents plans, builds, tests
and reviews a change, coordinating only through files on a shared bus. This glossary fixes
the words those agents and their operators use, because the agents read these words.

## Language

### The work

**Workstream**:
One feature being carried to completion, identified by a slug and owned by exactly one
branch name across every repository it touches. Survives across several runs.
_Avoid_: pipeline (ambiguous — see below), epic, effort

**Run**:
One pass of the phase sequence over a workstream, from spec to done. A workstream may need
several: waves, a follow-up, a resumed attempt. Identified by a `runId`.
_Avoid_: session, execution, cycle

**Wave**:
A run that continues a workstream another run began, on the same branch.
_Avoid_: phase 2, part 2, follow-up

**Pipeline**:
The machinery itself — the agents, the bus and the phase sequence. Never a unit of work.
Say *workstream* for the thing being built and *run* for one pass over it.

### The places

**Bus**:
The directory of files a run coordinates through. One bus per run; never shared, never
committed, always disposable.
_Avoid_: pipeline dir, state dir, workspace

**Container**:
A workstream's working directory, shaped like the repos root, holding one worktree per
service the workstream touches.
_Avoid_: worktree (that is one service's checkout inside it), sandbox

**Repos root**:
The directory whose children are the service repositories. Not itself a repository.
_Avoid_: monorepo, workspace root, project root

**Service**:
One repository the pipeline can change, named in the registry. Carries its own test and
build commands and its own fix budget.
_Avoid_: repo (use for the git repository itself), module, component

### The people

**Team**:
The agents working one run - planner, coder, tester, reviewer, and the operator when a run
needs one. A metaphor with teeth: each has its own tools and its own permissions.

**Operator**:
The agent that runs things and reports what happened — deploy, rebuild, restart, diagnose
a broken environment. Reports evidence (command, exit code, what changed, what to verify),
never a verdict. Never writes feature code. Optional: spawned only when the plan names
such a task.
_Avoid_: devops agent, deployer, runner

**Orchestrator**:
The conductor. Advances phases, spawns agents, makes routing decisions, and assesses what
they report. Never plans, writes, tests, reviews or deploys itself.
_Avoid_: controller, driver, manager

### The moments

**Gate**:
A hard stop where the run waits for a human. Spec gate confirms the acceptance criteria;
finalize gate approves the plan and creates the worktrees.
_Avoid_: checkpoint, approval step, pause

**Fix loop**:
The coder↔tester cycle that runs until tests are green or the budget is spent. The budget
is per service, never shared.
_Avoid_: retry loop, iteration cap

**Work completed**:
QA is green for the whole run. Set by `qa-check`, never by hand. What is left is the
human's: merge, deploy, verify, close.
_Avoid_: done (ambiguous), shipped, finished

**Completed**:
A human's stamp that work-completed work is deployed. One button in the hall, or
`pipe.py complete`. No agent ever sets it.
_Avoid_: closed (that is `finish`), released

**Estimate**:
Minutes of agent work, set per task by the planner at plan time from a size and a
complexity, and derived per phase by the bus. Counts time on the clock: parallel services
cost the longest chain, not the sum.
_Avoid_: ETA (say *expected* or *likely by* for a clock time), story points

**Waiting on you**:
Time a run spent at a gate or blocked. Not work, never estimated, and it pushes the
finish time out. *Paused* is the same for a silence over 15 minutes while running.
_Avoid_: idle, downtime

**Stale**:
A run claiming to be running whose bus has not been written to recently. Distinct from
*blocked* (known to be stuck) and *awaiting approval* (legitimately idle).
_Avoid_: hung, dead, stuck

### The identity

**Slug**:
The name of a workstream, derived from its spec document's path. Names the bus directory,
the branch (`feature/<slug>`), the container and the dashboard route.
_Avoid_: id, name, key
