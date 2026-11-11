---
name: test-scenarios
description: Rules for writing tests from use cases as Gherkin scenarios (Given / When / Then, the Cucumber format) in plain domain words, so a non-developer can read and review them. Covers what to test per use case, declarative wording, independent and deterministic scenarios, reusable steps, and Playwright UI journeys (playwright-bdd or test.step). Use when writing acceptance criteria, authoring or reviewing tests, when a review finding cites a rule id such as T2, or when asked to write BDD, Cucumber or Playwright scenarios.
---

# Test scenarios

A test proves a use case, so it is written in the use case's words. Every scenario is
Gherkin, the format Cucumber reads (https://cucumber.io): a title that states the
behaviour, then **Given** a context, **When** one action, **Then** the outcome. Written this
way, the person who asked for the feature can review the tests without reading code.
The wording rules follow Cucumber's own guidance ("Writing better Gherkin" and
"Anti-patterns" in its docs). [RUNNERS.md](RUNNERS.md) covers running scenarios in each
language, and [PLAYWRIGHT.md](PLAYWRIGHT.md) covers browser journeys.

## Gherkin always, Cucumber where the repo has it

- **The wording is not optional.** Acceptance criteria, `scenarios.json` and test names are
  always written as scenarios.
- **The tooling follows the repo.** Where the repo already runs Cucumber or playwright-bdd,
  write `.feature` files and step definitions. Where it does not, write tests in its own
  framework and keep the shape: the test is named after the scenario title, and its body
  follows the Given/When/Then lines, as `test.step` in Playwright, or as sections or
  comments elsewhere.
- **Adopting Cucumber in a repo is a planned task, never a side effect.** It adds a
  dependency and a step-definition layer someone has to maintain.
- **The repo's own test conventions win** over anything here, as with the design rules.

## A scenario, done well

```gherkin
@AC2 @negative
Scenario: An expired invitation cannot be accepted
  Given Priya was invited to the Finance workspace 8 days ago
  When Priya accepts the invitation
  Then she is told the invitation has expired
  And she is not a member of the Finance workspace
```

It names one behaviour. It uses words the business uses and none about screens or code, so
it reads the same whether Priya clicks a link, calls the API or uses a phone. Its tags say
which acceptance criterion it proves and what kind of path it is.

## The rules

| ID | Level | Rule | Spot it | Fix |
|---|---|---|---|---|
| T1 | must | **One scenario per behaviour, from a use case.** Every acceptance criterion has at least one scenario. Each scenario proves one behaviour, with one When, and its title states that behaviour as a fact. | a criterion with no scenario; several Whens; a title like `test login` | split it into one scenario per behaviour, and retitle each as the rule it proves |
| T2 | must | **Say what, not how.** Steps describe what the person or system does, never the mechanics: no clicks, field names, URLs, selectors, SQL or HTTP verbs. Ask Cucumber's question: *will this wording change if the implementation does?* | `When I click "Submit"`, `Given I visit "/login"`, `When I enter "x" in the email field` | name the intent (`When Bob logs in`) and move the mechanics into the step definition |
| T3 | must | **Given, When and Then mean context, action and outcome.** Given sets up state and performs no action under test. When is the action under test. Then checks something a user or a caller can observe, not internal state. And and But continue the line above. | an action in a Given; a check in a When; a Then reading a private field or a DB row the user never sees | move each line to the keyword its job belongs to; assert through the public interface |
| T4 | should | **Domain words and named people.** Use the project's glossary (CONTEXT.md when it exists) and named personas with a meaning (`Free Frieda`), not `user1`. No technical jargon. | `user1`, `the DTO`, `a 403`, `the record` | rename to the glossary term and a persona whose name says what matters about them |
| T5 | should | **Short and single-minded.** Three to seven steps. Background only for context every scenario in the file shares, at most four lines. No conjunction steps (`Given I have X and I am on Y`), which Cucumber lists as an anti-pattern. | a scenario you have to scroll; a long Background; `and` inside one step | split the conjunction step into two; push setup detail into the step definition; split the scenario |
| T6 | should | **Scenario Outline for the same behaviour over data,** and only for that. The Examples columns name the rule being varied. | copied scenarios that differ only in values; an Outline whose rows test different behaviours | merge copies into one Outline with a meaningful Examples table; split an Outline whose rows diverge |
| T7 | must | **Cover the paths that matter.** For each use case: the happy path, every failure the use case can produce (each typed error, design rule D10), and the edges at its boundaries (empty, maximum, duplicate, not allowed, concurrent where it applies). Tag each one `@happy`, `@negative` or `@edge`. | only the happy path; an error the code throws that no scenario reaches | add one scenario per missing failure and boundary |
| T8 | must | **Independent and deterministic.** Each scenario creates its own data, passes alone and in any order, and shares no state with other scenarios. No sleeps: wait for a condition, inject the clock, and seed randomness. | `sleep(`, `waitForTimeout`; order-dependent scenarios; shared accounts | build fixtures per scenario; replace sleeps with condition waits or a fake clock |
| T9 | should | **Reusable steps, organised by domain concept.** Step definitions are grouped by concept (accounts, invitations), not by feature file. There is one definition per phrase, and parameters use Cucumber expressions (`{string}`, `{int}`) rather than regular expressions. | one steps file per feature file; near-duplicate phrases; regex-heavy step patterns | merge duplicates into one parameterised step in the concept's file |
| T10 | should | **Thin steps.** A step definition calls the system through its public interface, or through page or screen objects. Checks live only in Then steps. No branching inside a step. | `if` in a step; checks in a Given or When; raw SQL to arrange state where an API exists | move the logic into a helper or page object; arrange state through the public interface |
| T11 | must | **Traceable.** Every scenario names the acceptance criterion it proves (`@AC3` tag or `criteriaRef`), and every criterion is proven by at least one scenario. | an untagged scenario; a criterion no scenario names | add the tag; write the missing scenario |
| T12 | should | **Run each scenario at the cheapest level that proves it.** Business rules run against the service or API. A browser runs only for journeys that need one: navigation, rendering, a real user flow across pages. | every rule driven through the UI; a 40-scenario browser suite for validation messages | push rule scenarios down to the API or service, and keep a few UI journeys |
| T13 | must | **Browser steps find things the way a person does.** Locate elements by role, label or visible text (`getByRole`, `getByLabel`), never by CSS or XPath tied to layout. Rely on the runner's auto-waiting, and check what the user sees. | `.btn-primary > span`, `//div[3]`, `nth-child`; hard waits | switch to role- or label-based locators; delete the hard waits (PLAYWRIGHT.md) |

## Writing scenarios (planner, tester, developer)

- **Spec and plan:** write each acceptance criterion as one scenario in plain words, with
  its id. This is what the person approves at the gate, so it must read without code.
- **Tester:** turn each criterion's scenario into the full set for T7, write them to
  `scenarios.json` with their Gherkin lines and tags, then implement them as tests per
  "Gherkin always, Cucumber where the repo has it" above.
- **Self-check before you hand off:** every criterion has a scenario (T1, T11); there are no
  clicks, URLs or selectors in the wording (T2); each keyword does its own job (T3); every
  failure and edge is covered (T7); there are no sleeps, no shared state, and each test
  runs alone (T8); browser locators find things the way a person does (T13).

## Reviewing scenarios

- Read the scenarios before the code: they should tell you what was built.
- Cite the rule on each finding (`"rule": "T2"`). Severity works the same way as for the
  design rules:
  - a **must** rule broken by this diff is `blocking`;
  - a **should** rule broken by this diff is `major`, or `minor` if trivial;
  - a problem in tests the diff did not touch is at most `minor`.
