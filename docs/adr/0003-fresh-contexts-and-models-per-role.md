# ADR-0003 — Fresh contexts, a model per role, and usage limits as a pause

**Status:** accepted · **Date:** 2026-10-30

## Context

The `janus-approve-fido2` run (2026-10-28: 5 services, 11 tasks) was measured from its
transcripts: 1,053 API calls, 271M cache-read tokens, about $198 at list prices. Two habits
made up three quarters of that, and neither came from the design:

- **The orchestrator ran in a long chat.** `/ship` began in a chat that already held 492k
  tokens, which reached 853k. The orchestrator is a model, and each of its 157 turns
  re-read all of it: 104.6M cache reads, about 30% of the run.
- **Two coders each carried a whole service.** One context grew from 19k to 438k over five
  tasks, the other to 425k over three. Together they were about 45% of the run.

A comparable harness (`my-harness`, a TypeScript loop that starts every ticket in a fresh
`claude -p`) spends nothing on coordination and never lets a context build up. A subagent's
fixed cost here was about 19k tokens on its first call, so starting fresh is cheap; carrying
context is not.

## Decision

1. **`/ship` starts in a fresh chat.** `hooks/ao-hooks.js` stops `/ship` and
   `/ship-from-spec` once in a chat past 120k tokens of context, read from the transcript's
   last reply. Sending the same command again within ten minutes runs it there anyway, so
   the person decides once. When the model invokes the skill itself it is denied in the
   same chat and told not to retry: only a typed confirmation counts.
2. **One fresh coder per two tasks.** `pipe.py next` names them in plan order with their
   dependencies met, as code rather than the orchestrator's judgement. The next coder
   picks up from the bus and git (`changes.json`, `git log`), not from a predecessor's
   memory.
3. **A model per role, in each agent's frontmatter.** Opus where design is decided and
   judged; Sonnet where it is carried out.
   - `planner: opus`: the plan records the design - files, signatures, the tests that
     prove each use case - and everything after it follows that.
   - `reviewer: opus`: the independent check is the one place design drift is caught.
     Tests catch a wrong result, not a wrong shape, so a cheaper reviewer would weaken
     the gate this pipeline exists for. Reviews were about 10% of the measured run.
   - `coder`, `tester`, `operator: sonnet`: they carry out a plan that already names the
     interfaces and the cases. The fix loop spawns its coder with `model: "opus"` from
     iteration 2, the iteration that must change strategy (ADR-0002), so a coder that is
     struggling gets the stronger model and one that is not does not pay for it.

   To change a default, edit that one line.
4. **A usage limit is a pause, not a death.** Claude Code waits for the reset and continues
   by itself (`autoContinueAtUsageLimit`). The same hook script writes
   `~/.agent-orchestration/usage-limit.json` on a `rate_limit` stop and removes it when
   Claude Code resumes. The hall shows one bar for the pause instead of calling every
   running team dead, and asks for you only when Claude Code is waiting on you. A subagent
   cut off by the limit is resumed, not re-spawned, and costs no fix iteration.

## Consequences

- Estimated on the measured run, (1) and (2) bring it from about $198 to about $120. That is
  an estimate, and the next real run should be measured the same way to confirm it.
- A long-lived chat is still allowed. It costs one extra command.
- Each coder re-reads the plan and the files its tasks touch, about 20–40k tokens per pair.
  That is the price of a fresh context, and it is far below what a carried one costs.
- `hooks/` is the plugin's first hook. It runs in Claude Code, so the dashboard still never
  spawns a process (spec section 14).
- `CLAUDE_CODE_SUBAGENT_MODEL_FORCE=1` overrides the per-role models for anyone who wants
  one model everywhere.
