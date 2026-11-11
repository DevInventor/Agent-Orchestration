# Running scenarios, per language

Cucumber runs `.feature` files in most languages. Pick the runner for the language of the
production code. This is Cucumber's own advice: "We recommend choosing an implementation for
the same platform or programming language as the production code."

| Language | With feature files | Status |
|---|---|---|
| Java / Kotlin | Cucumber-JVM, on the JUnit Platform | official (github.com/cucumber) |
| JavaScript / TypeScript | cucumber-js (`@cucumber/cucumber`); for browser journeys, playwright-bdd (PLAYWRIGHT.md) | official; playwright-bdd is community, MIT |
| Go | godog | official (github.com/cucumber) |
| Ruby | cucumber-ruby | official |
| C# / .NET | Reqnroll, the open-source continuation of SpecFlow | community |
| Python | behave, or pytest-bdd as a pytest plugin | community |

## Without feature files: keep the shape

A repo that does not run Cucumber still gets readable tests. The test name is the scenario
title, and the body follows the Given/When/Then lines in the same order and the same words.

| Framework | Shape |
|---|---|
| JUnit 5 | `@DisplayName("An expired invitation cannot be accepted")`, with `// Given`, `// When` and `// Then` sections in the body |
| Jest / Vitest | `it('an expired invitation cannot be accepted', …)` inside `describe('Workspace invitations')`, with `// Given`, `// When` and `// Then` sections |
| Playwright | `test('An expired invitation cannot be accepted @AC2', …)`, with one `test.step('Given …')` per line (PLAYWRIGHT.md) |
| pytest | `def test_an_expired_invitation_cannot_be_accepted():`, with `# Given`, `# When` and `# Then` sections |
| Go | `t.Run("an expired invitation cannot be accepted", …)`, with `// Given`, `// When` and `// Then` sections |
| xUnit / NUnit | `[Fact(DisplayName = "An expired invitation cannot be accepted")]`, with `// Given`, `// When` and `// Then` sections |

The scenario's Gherkin lines also live in `pipeline/test/scenarios.json`, so they can be
reviewed in one place, whichever form the tests take.

## Adopting Cucumber in a repo

It is worth adopting when people outside engineering review or write the scenarios, or
when the same steps serve many scenarios. It is not worth adopting for a handful of tests
read only by developers. Adopting it is a planned task with four parts:

1. Add the runner for the repo's language from the table above.
2. Create `features/` and a steps folder organised by domain concept (T9).
3. Wire it into the repo's test command, so CI runs it.
4. Convert one existing journey as the worked example for the rest.
