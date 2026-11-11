# ADR-0004 — One language-agnostic design rulebook, self-checked and cited by id

**Status:** accepted · **Date:** 2026-10-30

## Context

The pipeline held code to the plan, the tests and the reviewer's judgement, but not to a
shared design. Two runs of the same team could produce two shapes for the same thing.

GTID-Vault solved this for one Java codebase. Its ADR-0008 rulebook is enforced as build
checks: about 80 ArchUnit rules across 15 classes, 6 PMD guardrails (thin controller,
cognitive complexity 15, nesting 3, NPath 200, god class, 100-token duplication) and ten
contract guards. Every failure names the skill that explains the fix, and exceptions live in
a derogations log. Measured across 31 agent sessions on that code, the rules fired twice
(the same naming rule), both fixed by the coder in the same turn. They cost no fix
iterations and blocked no runs. They are cheap because the coder runs them before handing
off, and because they were written from the code as it already was.

Those rules are Java- and Spring-specific. The principles behind them are not.

## Decision

1. **`skills/design-rules`** states 23 rules (D1–D23) that hold in any language. Each
   GTID-Vault rule family maps to the principle behind it:
   - **Structure:** layering, package vocabulary and stereotypes become one-way layers,
     isolated modules, no cycles, one layout, no dumping grounds and naming (D1–D6).
   - **Boundaries:** DTO, validation and the thin-controller guardrail become D7–D9.
   - **Errors:** the error-handling rules become D10–D12.
   - **Wiring and cross-cutting concerns:** coding rules, caching and transactions become
     D13–D16.
   - **Size:** the PMD guardrails become D17–D19.
   - **Contracts:** the contract guards become one source of truth (D20) and variation as
     data (D21).
   - **Shapes and tests:** base shapes become D22, and test hygiene becomes D23.

   Each rule has a fix recipe under the same id in `FIXES.md`. `LANGUAGES.md` gives the
   idiom and the native enforcement tool per language.
2. **The repo's own rules win.** A repo's CLAUDE.md, ADRs, architecture tests and lint
   config are more specific and already enforced. This rulebook fills the gaps, and asks for
   *one* way of doing a thing, not *this* way.
3. **The planner designs to the rules, and the coder checks against them before hand-off.**
   The coder runs the self-check on each task's changes before committing it, which is what
   made the rules nearly free in GTID-Vault.
4. **The reviewer cites a rule id on every design finding.** `pipe.py review` rejects a
   finding that cites a rule the table does not define. Severity follows the rule's level:
   - a `must` rule broken by the diff is `blocking`;
   - a `should` rule broken by the diff is `major`;
   - a violation in code the diff did not touch is at most `minor`.

   An old repo is therefore never blocked by its own history.
5. **Exceptions are decisions, not workarounds.** An exception is recorded in the repo's
   decision log and referenced at the site. Inside a run, the coder raises it as a
   `question` rather than deciding alone.

## Consequences

- Design is consistent across runs and across developers. The skill also works outside the
  pipeline, as `/agent-orchestration:design-rules`.
- Without build checks, a rule holds only as well as the self-check and the review. A repo
  that wants GTID-Vault's guarantee adds the native tool for it, from `LANGUAGES.md`, as a
  planned task.
- **The cost is small.** The coder reads SKILL.md, about 11k characters or 3k tokens,
  once per spawn, and the self-check takes minutes. The risk to speed is a reviewer blocking on something that is
  not really a violation. That is why only `must` rules block, and only on code the diff
  changed.
- S67 keeps the rule table and the fix recipes in sync in both directions, the way
  GTID-Vault's `SkillRuleSyncGuardTest` keeps rules and skills in sync.
