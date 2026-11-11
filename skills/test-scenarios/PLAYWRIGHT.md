# Scenarios as Playwright tests

Browser journeys are where Gherkin pays off most: a UI test written click by click is the
hardest test to review and the first to break. There are two ways to keep Playwright tests
readable. Use whichever the repo already has.

## With playwright-bdd (when the repo uses it, or a task adopts it)

playwright-bdd (MIT, https://github.com/vitalets/playwright-bdd) turns `.feature` files into
native Playwright tests. The Playwright runner stays in charge, so fixtures, auto-waiting,
parallel runs, sharding, traces, screenshots and the HTML report all keep working.

```js
// playwright.config.js
import { defineConfig } from '@playwright/test';
import { defineBddConfig } from 'playwright-bdd';

const testDir = defineBddConfig({ features: 'features/**/*.feature', steps: 'features/steps/**/*.js' });
export default defineConfig({ testDir, reporter: 'html' });
```

```gherkin
# features/invitations.feature
Feature: Workspace invitations

  @AC2 @negative
  Scenario: An expired invitation cannot be accepted
    Given Priya was invited to the Finance workspace 8 days ago
    When Priya accepts the invitation
    Then she is told the invitation has expired
```

`page` is Playwright's own fixture. `api` and `inbox` stand for the repo's own fixtures
(an API client that arranges data, and a test mailbox); write them once with
`test.extend` and reuse them in every step.

```js
// features/steps/invitations.steps.js - grouped by concept, not by feature file (T9)
import { expect } from '@playwright/test';
import { createBdd } from 'playwright-bdd';
const { Given, When, Then } = createBdd();

Given('{word} was invited to the {word} workspace {int} days ago', async ({ api }, who, ws, days) => {
  await api.invite(who, ws, { sentDaysAgo: days });          // arrange through the API (T10)
});
When('{word} accepts the invitation', async ({ page, inbox }, who) => {
  await page.goto(await inbox.invitationLink(who));
  await page.getByRole('button', { name: 'Accept invitation' }).click();   // T13
});
Then('she is told the invitation has expired', async ({ page }) => {
  await expect(page.getByRole('alert')).toContainText('expired');
});
```

Run it with `npx bddgen && npx playwright test`. `bddgen` generates the test files from the
features, so commit the features and the steps, not the generated files. playwright-bdd
also publishes an agent skill (`npx skills add vitalets/playwright-bdd`) that grounds new
scenarios in the repo's existing steps.

## Without a new dependency: `test.step`

Plain Playwright gives the same reading experience. Name the test after the scenario, and
wrap each Gherkin line in `test.step`. The steps then appear, in that wording, in the HTML
report and the trace viewer.

```ts
test('An expired invitation cannot be accepted @AC2 @negative', async ({ page, api, inbox }) => {
  await test.step('Given Priya was invited to the Finance workspace 8 days ago', async () => {
    await api.invite('Priya', 'Finance', { sentDaysAgo: 8 });
  });
  await test.step('When Priya accepts the invitation', async () => {
    await page.goto(await inbox.invitationLink('Priya'));
    await page.getByRole('button', { name: 'Accept invitation' }).click();
  });
  await test.step('Then she is told the invitation has expired', async () => {
    await expect(page.getByRole('alert')).toContainText('expired');
  });
});
```

Tags in the title (`@AC2`) can be filtered with `--grep`, so `npx playwright test --grep @AC2`
runs the proof for one criterion.

## Improving an existing Playwright suite

Work through a click-by-click suite one journey at a time:

1. **Write the scenario first,** in plain words, from the use case the test was meant to
   prove. If no one can say which use case it was, the test is a candidate for deletion.
2. **Replace layout locators** (CSS, XPath, `nth-child`) with `getByRole`, `getByLabel` or
   `getByText`. Add an accessible name to the app where none exists; that also fixes
   accessibility (T13).
3. **Delete `waitForTimeout` and other fixed waits.** Playwright's `expect` and actions
   auto-wait. Wait for a condition, not a number (T8).
4. **Arrange through the API, not the UI.** Log in and seed data with a fixture or an API
   call. Only the behaviour under test goes through the browser (T10, T12).
5. **Move business-rule checks down** to API or service tests, and keep the browser suite to
   real journeys (T12).
6. **Give each test its own data and account,** so it passes alone and in parallel (T8).
