import type { Page } from '@playwright/test'
import { advanceUntil, finishLoading, openFrozen } from './support/clock'
import { waitingForApprover } from './support/flows'
import { goTo, switchUser } from './support/people'
import { record } from './support/record'
import { expect, test } from './support/test'

const attention = (page: Page) => page.getByRole('region', { name: 'Needs a person' }).locator(':scope > ul > li h3')
const fold = (page: Page) => page.locator('details', { has: page.locator('summary', { hasText: /up to date$/ }) })
const rowOf = (page: Page, name: string) => page.getByRole('article', { name, exact: true })

async function checkNowUntilWaiting(page: Page): Promise<void> {
  await page.getByRole('button', { name: 'Check now' }).click()
  await page.waitForURL(/\/runs\/run_demo/)
  await advanceUntil(page, waitingForApprover(page))
}

test('an Operator sees what needs a person first, with the up to date software folded', async ({ page }, info) => {
  await openFrozen(page, '/software')
  await expect(attention(page)).toHaveText(['FastAPI', 'LangGraph', 'Terraform'])
  await expect(rowOf(page, 'FastAPI').getByText('GitHub answered 404 Not Found.'), 'a row that cannot be checked says why').toBeVisible()
  await expect(rowOf(page, 'LangGraph')).toContainText('Behind')
  await expect(fold(page).locator('summary')).toHaveText('3 up to date')
  await expect(rowOf(page, 'n8n'), 'up to date software stays folded').toBeHidden()
  await expect(page.getByText('Checked every Monday at 9:00, set by Alice.')).toBeVisible()
  await expect(page.getByText('Next check Mon 30 Nov, 9:00.')).toBeVisible()
  await expect(page.getByText('Scheduled checks count as your work, so another Approver approves them.')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Check now' })).toBeVisible()
  await record(page, info, 'software-operator')

  await fold(page).locator('summary').click()
  await expect(rowOf(page, 'n8n')).toContainText('From MOCK-140, Done 20 Nov')
  await expect(rowOf(page, 'Redis')).toContainText('Newest at the first check')
})

test('an Approver sees the page read-only, and who cannot approve a scheduled check', async ({ page }, info) => {
  await openFrozen(page, '/software')
  await switchUser(page, 'Bob')
  await expect(attention(page)).toHaveText(['FastAPI', 'LangGraph', 'Terraform'])
  await expect(page.getByText("Scheduled checks count as Alice's work, so Alice can't approve them.")).toBeVisible()
  await expect(page.getByText('Operators add and remove software.')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Check now' }), 'only an Operator starts a check').toHaveCount(0)
  await expect(page.getByRole('button', { name: /^Remove/ }), 'only an Operator removes software').toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Change' }), 'only an Operator changes the schedule').toHaveCount(0)
  await expect(page.getByRole('heading', { name: 'Add software' })).toHaveCount(0)
  await record(page, info, 'software-approver')
})

test('an Operator adds and removes software, with problems shown at each field', async ({ page }, info) => {
  await openFrozen(page, '/software')
  await page.getByRole('button', { name: 'Add', exact: true }).click()
  const name = page.getByLabel('Name', { exact: true })
  const repo = page.getByLabel('GitHub repository')
  await expect(name).toHaveAttribute('aria-invalid', 'true')
  await expect(name, 'focus goes to the first field with a problem').toBeFocused()
  await expect(page.getByText("Write the software's name.")).toBeVisible()
  await expect(page.getByText('Write the GitHub repository, such as langchain-ai/langgraph.')).toBeVisible()
  await record(page, info, 'software-add-problems')

  await name.fill('Grafana')
  await repo.fill('https://github.com/grafana/grafana/releases')
  await page.getByLabel('Our version (optional)').fill('v12.0.1')
  await page.getByRole('button', { name: 'Add', exact: true }).click()
  await advanceUntil(page, page.getByText('Added Grafana. The next check reads it.'))
  await expect(rowOf(page, 'Grafana')).toContainText('12.0.1')
  await expect(rowOf(page, 'Grafana')).toContainText('Not checked yet')
  await expect(attention(page)).toHaveText(['FastAPI', 'LangGraph', 'Grafana', 'Terraform'])

  await name.fill('Grafana again')
  await repo.fill('grafana/grafana')
  await page.getByRole('button', { name: 'Add', exact: true }).click()
  await advanceUntil(page, page.getByText('grafana/grafana is already on the list.'))

  await page.getByRole('button', { name: 'Remove LangGraph' }).click()
  await expect(page.getByRole('button', { name: 'Keep' }), 'focus waits on the safe choice').toBeFocused()
  await page.getByRole('button', { name: 'Keep' }).click()
  await expect(page.getByRole('button', { name: 'Remove LangGraph' }), 'focus returns to Remove after Keep').toBeFocused()

  await page.getByRole('button', { name: 'Remove FastAPI' }).click()
  const confirm = page.getByRole('group', { name: 'Remove FastAPI?' })
  await expect(confirm).toContainText('Remove FastAPI from the list?')
  await record(page, info, 'software-remove-confirm')
  await confirm.getByRole('button', { name: 'Remove', exact: true }).click()
  await advanceUntil(page, page.getByText('Removed FastAPI.'))
  await expect(attention(page)).toHaveText(['LangGraph', 'Grafana', 'Terraform'])
  await expect(page.getByRole('heading', { name: 'Needs a person' }), 'focus lands on the list, not on the page top').toBeFocused()
})

test('a watchlist with nothing on it explains itself in one sentence and offers the form', async ({ page }, info) => {
  await openFrozen(page, '/software')
  for (const name of ['FastAPI', 'LangGraph', 'Terraform']) {
    await page.getByRole('button', { name: `Remove ${name}` }).click()
    await page.getByRole('group', { name: `Remove ${name}?` }).getByRole('button', { name: 'Remove', exact: true }).click()
    await advanceUntil(page, page.getByText(`Removed ${name}.`))
  }
  await fold(page).locator('summary').click()
  for (const name of ['n8n', 'PostgreSQL', 'Redis']) {
    await page.getByRole('button', { name: `Remove ${name}` }).click()
    await page.getByRole('group', { name: `Remove ${name}?` }).getByRole('button', { name: 'Remove', exact: true }).click()
    await advanceUntil(page, page.getByText(`Removed ${name}.`).or(page.getByRole('heading', { name: 'No software yet' })))
  }
  await expect(page.getByRole('heading', { name: 'No software yet' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Add the first software' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Check now' }), 'nothing to check').toHaveCount(0)
  await record(page, info, 'software-empty')
})

test('an Operator changes the schedule and becomes its owner, or turns it off', async ({ page }, info) => {
  await openFrozen(page, '/software')
  await switchUser(page, 'Carol')
  await page.getByRole('button', { name: 'Change' }).click()
  await expect(page.getByLabel('Day'), 'focus moves into the form').toBeFocused()
  await page.getByLabel('Day').selectOption('every_day')
  await page.getByLabel('Time in Singapore').fill('06:30')
  await expect(page.getByText("Saving makes you the schedule owner, so you can't approve scheduled checks.")).toBeVisible()
  await record(page, info, 'software-schedule-edit')

  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await advanceUntil(page, page.getByText('Checked every day at 6:30, set by Carol.'))
  await expect(page.getByText('Next check Sat 28 Nov, 6:30.')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Change' }), 'focus returns to Change').toBeFocused()

  await switchUser(page, 'Alice')
  await advanceUntil(page, page.getByText("Scheduled checks count as Carol's work, so Carol can't approve them."))
  await page.getByRole('button', { name: 'Change' }).click()
  await page.getByRole('button', { name: 'Turn off' }).click()
  await advanceUntil(page, page.getByText('Not checked on a schedule. A check starts only when an Operator presses Check now.'))
  await expect(page.getByRole('button', { name: 'Set a schedule' })).toBeVisible()
})

test('Check now opens the run, and the rows follow the check', async ({ page }, info) => {
  test.setTimeout(150_000)
  await openFrozen(page, '/software')
  await checkNowUntilWaiting(page)
  for (const stop of ['agent:read_versions', 'draft', 'gate', 'write:jira', 'done']) {
    await expect(page.locator(`li[data-stop="${stop}"]`), `the line has its ${stop} stop`).toHaveCount(1)
  }
  const approval = page.getByRole('region', { name: 'Approval' })
  await advanceUntil(page, approval.getByText('You started this run, so another Approver must decide.'))
  await expect(approval.getByRole('heading', { name: '3 Jira tickets in MOCK' })).toBeVisible()
  await record(page, info, 'software-check-run')

  await goTo(page, 'Software')
  await advanceUntil(page, fold(page).locator('summary', { hasText: '2 up to date' }))
  await expect(attention(page)).toHaveText(['FastAPI', 'LangGraph', 'PostgreSQL', 'Redis'])
  for (const name of ['LangGraph', 'PostgreSQL', 'Redis']) {
    await expect(rowOf(page, name)).toContainText('Waiting for approval')
    await expect(rowOf(page, name).getByRole('link', { name: 'Open the approval' })).toBeVisible()
  }
  await expect(fold(page).locator('summary')).toHaveText('2 up to date')
  await record(page, info, 'software-after-check')
})

test('an approved check writes its tickets, and Mark Done moves our version', async ({ page }, info) => {
  test.setTimeout(180_000)
  await openFrozen(page, '/software')
  await checkNowUntilWaiting(page)

  await goTo(page, 'Software')
  await switchUser(page, 'Bob')
  await rowOf(page, 'Redis').getByRole('link', { name: 'Open the approval' }).click()
  await advanceUntil(page, page.getByRole('heading', { name: 'Approve 3 writes to Jira' }))
  await finishLoading(page)
  await expect(page.getByRole('article', { name: /^Write \d of 3$/ })).toHaveCount(3)
  await expect(page.getByText('If any of these tickets changes, your approval no longer applies.'), 'said once for the whole check').toHaveCount(1)
  const approve = page.getByRole('button', { name: 'Approve and write to Jira' })
  await expect(approve).toBeEnabled()
  await record(page, info, 'approval-check-bob')

  await approve.click()
  await advanceUntil(page, page.getByText(/^Written as MOCK-145/))
  await expect(page.getByText(/^Written as MOCK-143/)).toBeVisible()

  await goTo(page, 'Jira')
  const redis = page.getByRole('article', { name: 'Upgrade Redis from 8.2.0 to 8.2.1' })
  await expect(redis).toContainText('To Do')
  await expect(redis.getByRole('button', { name: /^Mark Done/ }), 'Bob is an Approver only').toHaveCount(0)
  await switchUser(page, 'Alice')
  await redis.getByRole('button', { name: /^Mark Done/ }).click()
  await advanceUntil(page, redis.getByText('Done', { exact: true }))
  await expect(redis.getByRole('button', { name: /^Mark Done/ })).toHaveCount(0)
  await record(page, info, 'jira-mark-done')

  await goTo(page, 'Software')
  await advanceUntil(page, fold(page).locator('summary', { hasText: '3 up to date' }))
  await expect(attention(page)).toHaveText(['FastAPI', 'LangGraph', 'PostgreSQL'])
  await expect(rowOf(page, 'LangGraph')).toContainText('Ticket open')
  await fold(page).locator('summary').click()
  const moved = rowOf(page, 'Redis')
  await expect(moved).toContainText('Up to date')
  await expect(moved).toContainText('8.2.1')
  await expect(moved).toContainText(/From MOCK-14\d, Done 27 Nov/)
  await record(page, info, 'software-after-done')
})
