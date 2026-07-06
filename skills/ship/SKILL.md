---
name: ship
description: Ship a feature end-to-end with the 4-agent pipeline (plan -> implement -> test -> review -> QA), authoring the spec from the user's feature request. Use whenever the user runs /ship or asks to build a feature end-to-end with the planner/coder/tester/reviewer agent team and there is no spec doc yet. If a spec doc already exists, use ship-from-spec instead. Also use when a run needs to be resumed or inspected.
argument-hint: <feature description>
---

# /ship — author a spec, then ship it

Use this when there is **no spec doc yet**: you turn the user's raw feature request
into a spec, then run the full pipeline. (If the user already has a spec doc, use
**ship-from-spec** instead.)

The **feature to ship** is whatever the user gave when invoking `/ship`. If they
gave nothing, ask for a one-paragraph feature description before starting.

```bash
PIPE="python3 ${CLAUDE_PLUGIN_ROOT}/scripts/pipe.py"
```

## Init + author the spec  (phase: spec)
1. `$PIPE init --feature "<the feature the user gave /ship>"`.
2. Refine the raw request in `pipeline/spec.md` into crisp, testable acceptance
   criteria (a short bullet list). Overwrite the file.
3. `$PIPE event --agent orchestrator --type status --summary "Spec normalized: N acceptance criteria"`.

## Then run the pipeline
Now follow `${CLAUDE_PLUGIN_ROOT}/docs/orchestration-runbook.md` from the Plan phase
onward. It owns the rest of the run: plan → finalize gate → implement → test/fix loop
→ review → QA → done, for both single- and multi-service plans.
