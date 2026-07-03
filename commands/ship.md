---
description: Ship a feature end-to-end with the 4-agent pipeline (plan -> implement -> test -> review -> QA).
argument-hint: <feature description>
---

# /ship

The user wants to ship this feature through the multi-agent pipeline:

> $ARGUMENTS

Do this now:

1. Load the **ship-orchestrator** skill and follow it exactly. It owns the whole
   run: initializing the shared `./pipeline` bus, spawning the planner, then
   **presenting the plan and stopping for the user to reply `finalize`** before any
   code is written. After finalize it either runs the classic single-team loop (plan
   touches one service) or, for several services, drives them **phase-batched from the
   top level** — spawning all coders in one batch, then all testers, re-spawning only
   the services still failing (max 5 iterations **per service**) — then gates QA across
   all services.
2. If `$ARGUMENTS` is empty, ask the user for a one-paragraph feature description
   before starting.
3. Remind the user once, at the start, that they can watch progress live with
   `node ${CLAUDE_PLUGIN_ROOT}/ui/server.js` (opens the dashboard on
   http://localhost:4600).

Do not implement anything yourself in this command — you are the conductor;
the subagents do the work.
