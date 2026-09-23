---
name: ship
description: Ship a feature end-to-end with the 4-agent pipeline (plan -> implement -> test -> review -> QA), authoring the spec from the user's feature request. Use whenever the user runs /ship or asks to build a feature end-to-end with the planner/coder/tester/reviewer agent team and there is no spec doc yet. If a spec doc already exists, use ship-from-spec instead. Also use when a run needs to be resumed or inspected.
argument-hint: <feature description>
---

# /ship â€” author a spec, then ship it

Use this when there is **no spec doc yet**: you turn the user's raw feature request
into a spec, then run the full pipeline. (If the user already has a spec doc, use
**ship-from-spec** instead.)

The **feature to ship** is whatever the user gave when invoking `/ship`. If they
gave nothing, ask for a one-paragraph feature description before starting.

**Resolve the interpreter once, here.** On Windows `python3` is the Microsoft Store
alias stub: it is on PATH, so `command -v python3` finds it, and it exits non-zero with
*"Python was not found"* the moment an agent uses it. Resolve it by **running** it, and
hand the finished `$PIPE` down to every subagent â€” they do not repeat this.

```bash
PY=$(python3 -c 'import sys;print(sys.executable)' 2>/dev/null || command -v python)
PIPE="$PY ${CLAUDE_PLUGIN_ROOT}/scripts/pipe.py"
```

## Init + author the spec  (phase: spec)
1. **Name the workstream, then create its bus.** There is no spec doc yet, so the slug
   comes from the feature title â€” through `pipe.py`, never by eye, so a later wave
   derives the same name and lands on the same branch.
   ```bash
   $PIPE slug --title "<the feature the user gave /ship>"   # -> e.g. sso-logout-endpoint
   $PIPE init --slug "<slug>" --feature "<the feature>"   # no --spec: there is no doc yet
   ```
   `init` prints one JSON document; its **`busPath`** key is the resolved absolute
   bus path (`... | $PY -c 'import json,sys;print(json.load(sys.stdin)["busPath"])'`).
   The bus no longer lives at `./pipeline`, so from here on **bake that path in**:
   ```bash
   PIPE="$PY ${CLAUDE_PLUGIN_ROOT}/scripts/pipe.py --root <busPath>"
   ```
   Use that literal path for the rest of the run and hand it to every subagent you
   spawn â€” a subagent that guesses `./pipeline` writes to a bus nobody is reading.
1b. **Announce the branch.** Tell the user, in one line: every repository this
   workstream touches will use the branch **`feature/<slug>`**, fixed now, and the bus
   is at the path above. Nothing later can change the name.
2. **Start the dashboard â€” do not skip this.** Nothing else in the pipeline ever starts
   it, and the server is a passive file reader: if it is not running, the entire run is
   invisible. Launch it as a **background** Bash call so it outlives this turn:
   ```bash
   node "${CLAUDE_PLUGIN_ROOT}/ui/server.js" --pipeline "<the printed bus path>"
   ```
   A held port is not assumed to be ours — a stale dashboard from a finished run may hold it — so it steps to the next free port and prints the one it bound.
   Pass the **absolute** bus path as shown; the server resolves `--pipeline` against its
   own cwd, so a relative path silently watches the wrong directory.
   Then tell the user once: **the URL the server printed** (4600 unless it was taken, in which case it steps to the next free port and says so).
3. Refine the raw request in `<bus>/spec.md` into crisp, testable acceptance
   criteria (a short bullet list). Overwrite the file.
4. `$PIPE event --agent orchestrator --type status --summary "Spec normalized: N acceptance criteria"`.

## Then run the pipeline
Now follow `${CLAUDE_PLUGIN_ROOT}/docs/orchestration-runbook.md` from the Plan phase
onward, carrying the bus path with you. It owns the rest of the run: plan â†’ finalize
gate â†’ implement â†’ test/fix loop â†’ review â†’ QA â†’ done, for both single- and
multi-service plans.
