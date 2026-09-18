# The reviewer persists its own findings through `pipe.py`, not via the orchestrator

The reviewer was read-only (`Read, Grep, Glob`) and *returned* its analysis for the
orchestrator to write to disk. Measured across 22 real buses, that relay cost more than it
looked: 90 of 174 `finding` events were emitted by the orchestrator rather than the
reviewer, so every review passed in full through the longest-lived and most expensive
context in the run — and an LLM re-typing structured findings can silently drop one, merge
two, or soften a severity in the one artifact whose job is to be exact.

We therefore grant the reviewer `Bash` (**not** `Write` or `Edit`) and have it persist via
`pipe.py review --from <file>`, which validates the schema, writes `review.json`, and
renders `review.md` from it. The orchestrator now sees only a one-line summary.

## Considered Options

- **Reviewer returns findings, orchestrator writes them** (the original). Keeps the
  read-only guarantee but puts a lossy LLM copy step inside the audit trail, and pays for
  every review twice.
- **Grant the reviewer `Write`.** Removes the relay, but `Write` is unbounded — a reviewer
  that can overwrite a path can "fix" the code it is judging, which is the exact property
  the read-only design existed to prevent.
- **Grant `Bash`, write only through `pipe.py`** (chosen). `pipe.py` is already documented
  as the only sanctioned way to touch bus state; this makes the reviewer obey the house
  rule rather than be exempted from it by a human relay.

## Consequences

`Bash` is broader in raw capability than `Write`, so this rests on convention rather than
enforcement. It adds no *new* trust surface — the planner already runs with exactly this
grant and is likewise described as read-only — and it can be tightened with a permission
allowlist (`python3 */pipe.py *`) without changing the architecture.

Because findings now land on disk schema-validated rather than paraphrased, `pipe.py
qa-check` can read them reliably and refuse `done` while a `blocking` finding is
unresolved. That check is only trustworthy because of this decision.
