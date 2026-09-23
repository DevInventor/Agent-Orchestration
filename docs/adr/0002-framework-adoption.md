# ADR-0002 — Superpowers and grilling as the pipeline's process framework

**Status:** accepted · **Date:** 2026-09-23 · **Supersedes:** the conditional paragraph in
`docs/orchestration-runbook.md` ("if the superpowers plugin is installed, prefer
delegating…")

## Decision

Adopt **two** frameworks, bound to the phases each actually fits, and extend them with
local skills rather than replacing them:

- **`grilling`** (local skill, 833 B) at the two moments a human is present — the spec gate
  and the finalize gate. `grill-with-docs` where a decision deserves an ADR, because it
  chains `domain-modeling`, which is how `CONTEXT.md` and this directory get maintained.
- **`superpowers` 6.4.1** (official marketplace) for the unattended phases, one named skill
  per phase — never the whole set.
- **Local agent definitions remain the extension point.** A framework skill supplies the
  method; the agent file supplies this project's flavour — the bus contract, the ponytail
  ladder, watch-it-fail, and the artefact each phase must write.

## Why two, and not one

They are not the same kind of thing, and neither covers the other's ground.

`grilling` is a **human-in-the-loop interrogation**. Its own text says *"ask the questions
one at a time, waiting for feedback"* and *"do not enact the plan until I confirm"*. That is
exactly right for a gate and structurally impossible for the coder, tester and reviewer,
which run unattended between two gates. It also contains no implementation, testing or
review guidance — there is simply nothing in it to drive those phases with.

`superpowers` covers the unattended half, and the mapping onto our phases is close to 1:1.

## What this costs, recorded because it was measured and accepted

| | Size | ≈ tokens |
|---|---|---|
| All superpowers skills | 168,882 B | ~42k |
| `subagent-driven-development` alone | 32,577 B | ~8k |
| All six of our agent definitions combined | 24,478 B | ~6k |
| `grilling` | 833 B | ~200 |

Adoption **increases** token use; it does not reduce it. §13 of the engine spec names the
spawn preamble as the largest token line item, and AC10(a) had just shrunk every agent
preamble to a ~400 B cheatsheet. This decision knowingly spends part of that back.

Three things keep the bill bounded:

1. **One skill per phase, named.** An agent invokes the skill bound to its phase and no
   other. The framework is not loaded wholesale at any point.
2. **`subagent-driven-development` is the orchestrator's alone.** It is the largest skill
   and the most duplicative of what the runbook already does, so it loads once per run
   rather than once per agent spawn.
3. **Skills are invoked at the phase, not pasted into the preamble.** The cheatsheet still
   names the command set; the skill arrives only when that phase begins.

## What this does not buy

Recorded so it is not claimed later:

- **It does not standardise output.** No superpowers skill examined defines a JSON schema
  or an output format; they standardise method, not artefacts. Our standardisation comes
  from `pipe.py` owning the writes. `plan.json` and `results.json` are still written
  free-hand and unvalidated — that gap is P4 and is unaffected by this decision.
- **It does not improve portability.** Adapting to a repository is the service registry's
  job, and it already carries per-stack commands (`./gradlew test`, `./mvnw -q test`,
  `mvn -o verify`, `python -m unittest`) across four stacks in one estate.
- **It is prose, and prose has been ignored here before.** Every accuracy win this project
  has recorded came from a machine-checked guard; several prose rules were ignored at least
  once. The binding below is therefore asserted by a test, not merely written down.

## The bindings

| Phase | Who | Skill | Local flavour that overrides it |
|---|---|---|---|
| spec gate | user + orchestrator | `grilling` | acceptance criteria must be testable and numbered AC1..N |
| plan | planner | `superpowers:writing-plans` | output is `plan.json` with `services[]`, `acceptanceCriteria`, and a `criteriaRef` per task |
| finalize gate | user + orchestrator | `grilling` | the three decisions are `finalize` / `in-place` / `reject`, and nothing else |
| implement | coder | `superpowers:executing-plans` | commit each task; `diff.patch` is `git diff <base>...HEAD` |
| test | tester | `superpowers:test-driven-development` | watch it fail first; commit the tests; declare inherited reds with evidence |
| fix loop, K≥2 | coder | `superpowers:systematic-debugging` | iteration 2 must change strategy, not repeat iteration 1 |
| review | reviewer | `ponytail` review | persist through `pipe.py review --from`; no `Write`, no `Edit` (ADR-0001) |
| findings returned | coder | `superpowers:receiving-code-review` | verify the finding before implementing it |
| qa gate | orchestrator | `superpowers:verification-before-completion` | `pipe.py qa-check` is the gate; a green claim without it is not evidence |
| finish | orchestrator | `superpowers:finishing-a-development-branch` | `finish` plans by default; `--apply` merges all repos or none |
| whole run | orchestrator | `superpowers:subagent-driven-development` | the bus contract and the phase sequence win where they differ |

## Version pinning

`superpowers` is a plugin we do not control, and it shipped 6.3.0 → 6.4.1 during the period
this project has been running. Our agents resolve through a version-keyed cache that has
silently served a stale build three times. **The version is pinned at 6.4.1 in
`scripts/test_pipe.py`, and the suite fails when the installed version differs** — so an
upstream change that alters how every agent works is a red test rather than a mystery.

## Consequences

- A phase that names a skill which does not exist fails the suite, the same way a command
  named in an agent file but missing from `pipe.py`'s parser already does.
- Upgrading superpowers is a deliberate act: bump the pin, re-read the changed skills,
  re-run the suite.
- If the token cost proves worse than estimated in practice, the cheapest reversal is to
  drop `subagent-driven-development` first — it is the largest and the most duplicative of
  the runbook.
