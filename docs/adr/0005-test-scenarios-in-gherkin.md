# ADR-0005 — Test scenarios in Gherkin: the wording always, Cucumber where the repo runs it

**Status:** accepted · **Date:** 2026-10-30

## Context

The tester already authors "use-case and dataflow scenarios". Their steps were free text,
and acceptance criteria were a bullet list. Nothing made a test readable by the person who
asked for the feature, and nothing tied a test to the criterion it proves in a form a
reviewer could check at a glance.

Cucumber's Gherkin format (Given / When / Then) is the common answer. Cucumber's own
guidance has two key points:
- **Say what, not how.** "Will this wording need to change if the implementation does?"
- **Avoid the anti-patterns:** feature-coupled step definitions and conjunction steps.

Popular tutorials often show the opposite, a login scenario written click by click, which
is the style Cucumber's docs call imperative and brittle.

There are two costs to weigh:
- **Running Cucumber means a step-definition layer.** It is a dependency and a body of glue
  code someone has to maintain.
- **playwright-bdd** (MIT, actively maintained) runs `.feature` files on the Playwright
  runner without giving up its fixtures, traces or reports. Plain Playwright's `test.step`
  shows Gherkin-worded steps in the same report with no dependency at all.

## Decision

1. **`skills/test-scenarios` defines 13 rules (T1–T13).** They cover:
   - one behaviour per scenario, from a use case;
   - declarative wording, with Given, When and Then each doing its own job;
   - domain words, short scenarios, and Outlines only for data;
   - the happy, failure and edge paths;
   - independent, deterministic scenarios;
   - reusable, thin steps;
   - traceability to criterion ids;
   - the cheapest level that proves a scenario;
   - role-based browser locators.

   `PLAYWRIGHT.md` and `RUNNERS.md` cover execution, including how to improve an existing
   Playwright suite.
2. **The wording is mandatory everywhere.** The spec writes each acceptance criterion as a
   plain-words scenario with an id, so that is what the user approves at the gate. The
   tester's `scenarios.json` carries Gherkin lines and criterion ids, and test names are
   scenario titles.
3. **The tooling follows the repo.** Where a repo runs Cucumber or playwright-bdd, the
   tester writes `.feature` files and steps. Elsewhere, it writes tests in the repo's own
   framework, in the same shape. Adopting Cucumber is a planned task, never a side effect.
4. **The reviewer reads the scenarios before the code** and cites `T#` rules. Severity
   follows the same policy as the design rules (ADR-0004), and `pipe.py review` accepts
   only rule ids the two tables define.

## Consequences

- Acceptance criteria and tests become reviewable by people who do not read code, and each
  test names the criterion it proves.
- **No repo gains a dependency it did not choose.** The cost is a small amount of
  discipline in wording.
- A run's scenarios are in `scenarios.json`, ready for the board to render as Gherkin. That
  view is not built yet.
- S68 keeps the rule table, the agents that use it, and the review's accepted ids in sync.
