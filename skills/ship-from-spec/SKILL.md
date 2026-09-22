---
name: ship-from-spec
description: Ship a feature end-to-end with the 4-agent pipeline (plan -> implement -> test -> review -> QA) from an existing spec doc. Use whenever the user runs /ship-from-spec or already has a written spec/requirements doc and wants the planner/coder/tester/reviewer team to build it. The spec doc path is passed as the argument. If there is no spec doc yet, use ship instead. Also use when a run needs to be resumed or inspected.
argument-hint: <path to spec doc>
---

# /ship-from-spec — ship an existing spec

Use this when the user **already has a spec doc**: you load it and run the full
pipeline against it, skipping spec authoring. (If there is no spec yet, use **ship**,
which writes one from the feature description first.)

The **spec doc path** is whatever the user gave when invoking `/ship-from-spec`.
If they gave no path, ask for one. If the path does not exist or is empty, say so
and stop — do not invent a spec.

**Resolve the interpreter once, here.** On Windows `python3` is the Microsoft Store
alias stub: it is on PATH, so `command -v python3` finds it, and it exits non-zero with
*"Python was not found"* the moment an agent uses it. Resolve it by **running** it, and
hand the finished `$PIPE` down to every subagent — they do not repeat this.

```bash
PY=$(python3 -c 'import sys;print(sys.executable)' 2>/dev/null || command -v python)
PIPE="$PY ${CLAUDE_PLUGIN_ROOT}/scripts/pipe.py"
```

## Load the spec  (phase: spec)
1. Read the spec doc at the path the user gave.
2. **Name the workstream, then create its bus.** The slug is derived from the doc's
   path by `pipe.py`, never by eye — a later wave must derive the same one, or it lands
   on a second branch.
   ```bash
   $PIPE slug --spec "<the doc path>"                      # -> e.g. 009-messaging-hub
   $PIPE init --slug "<slug>" --spec "<the doc path>" --feature "<one-line title>"
   ```
   `init` prints one JSON document; its **`busPath`** key is the resolved absolute
   bus path (`... | $PY -c 'import json,sys;print(json.load(sys.stdin)["busPath"])'`).
   The bus no longer lives at `./pipeline`, so from here on **bake that path in**:
   ```bash
   PIPE="$PY ${CLAUDE_PLUGIN_ROOT}/scripts/pipe.py --root <busPath>"
   ```
   Use that literal path for the rest of the run and hand it to every subagent you
   spawn — a subagent that guesses `./pipeline` writes to a bus nobody is reading.
2b. **Announce the branch.** Tell the user, in one line: every repository this
   workstream touches will use the branch **`feature/<slug>`**, fixed now, and the bus
   is at the path above. Nothing later can change the name.
2c. **Start the dashboard — do not skip this.** Nothing else in the pipeline ever starts
   it, and the server is a passive file reader: if it is not running, the entire run is
   invisible. Launch it as a **background** Bash call so it outlives this turn:
   ```bash
   node "${CLAUDE_PLUGIN_ROOT}/ui/server.js" --pipeline "<the printed bus path>"
   ```
   It is idempotent — if a dashboard already holds the port it prints that and exits 0.
   Pass the **absolute** bus path as shown; the server resolves `--pipeline` against its
   own cwd, so a relative path silently watches the wrong directory.
   Then tell the user once: **http://localhost:4600**.
3. Write the spec into `<bus>/spec.md` (overwrite). Preserve the user's content;
   only add structure if it lacks crisp, testable acceptance criteria — in that case
   distill a short bullet list of criteria at the top and keep the original below.
4. `$PIPE event --agent orchestrator --type status --summary "Spec loaded from <path>: N acceptance criteria"`.

## Then run the pipeline
Now follow `${CLAUDE_PLUGIN_ROOT}/docs/orchestration-runbook.md` from the Plan phase
onward, carrying the bus path with you. It owns the rest of the run: plan → finalize
gate → implement → test/fix loop → review → QA → done, for both single- and
multi-service plans.
