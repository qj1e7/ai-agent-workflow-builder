import { randomUUID } from 'node:crypto'
import path from 'node:path'
import type { Page } from '@playwright/test'
import { expectAccessible } from '../support/axe'
import { assertClean, watchPage } from '../support/test'
import {
  connectMockModel,
  FOLLOW_UP,
  fixRow,
  heading,
  nextButton,
  NO_SCHEDULE,
  planIt,
  pressNext,
  RELEASE,
  rowOf,
  stepHeading,
  TEAMS,
  throughToReview,
  turnOn,
} from './support/newWorkflow'
import { expect, test } from './support/test'
import { devContext, OUT, shot } from './support/ui'

const settled = (page: Page) => page.waitForFunction(() => document.getAnimations().length === 0)
const mainMenu = (page: Page) => page.getByRole('navigation', { name: 'Main' }).filter({ visible: true })

test.beforeAll(async ({ baseURL }) => {
  await connectMockModel(String(baseURL))
})

test('alice sets up the follow-up ticket workflow, fixes one row, turns it on and test runs it, and bob’s yes writes the ticket', async ({ browser, backend }, info) => {
  const name = `p13 follow-up ${randomUUID().slice(0, 6)}`
  const context = await devContext(browser, 'alice')
  const page = await context.newPage()
  const watch = watchPage(page)
  await page.goto('/')
  await mainMenu(page).getByRole('link', { name: 'New workflow' }).click()
  await expect(heading(page)).toHaveText(stepHeading(1, 'Describe it'))
  await expect(heading(page)).toBeFocused()
  await planIt(page, FOLLOW_UP)
  await expect(heading(page), 'each step’s heading takes focus').toBeFocused()
  for (const label of ['When', 'Looks for', 'Does', 'Where it goes'] as const) await expect(rowOf(page, label)).toContainText('from your words')
  await fixRow(page, 'Looks for', 'Bug tickets in MOCK with no update for 14 days')
  await expect(rowOf(page, 'Looks for')).toContainText('changed by you')
  await expect(page.getByLabel('Jira project')).toHaveValue('MOCK')
  await shot(page, info, 'p13-07-step-2')
  await throughToReview(page, name)
  await expect(page.getByRole('main')).toContainText('Any Approver except you')
  const useCaseId = await turnOn(page)
  await shot(page, info, 'p13-07-done')

  const workflow = await backend.get<{ state: string; schedule: { day: string; at: string } | null }>('alice', `/api/v1/use-cases/${useCaseId}`)
  expect(workflow.state).toBe('on')
  expect(workflow.schedule).toMatchObject({ day: 'weekdays', at: '15:00' })

  await page.getByRole('button', { name: 'Do a test run now' }).click()
  await expect(page).toHaveURL(/\/runs\/[^/]+$/)
  const runId = /\/runs\/([^/?#]+)$/.exec(page.url())?.[1] ?? ''
  await backend.waitForState(runId, ['awaiting_approval'])
  const approvalId = await backend.approvalIdOf(runId)
  const asked = await backend.get<{ digest: string }>('bob', `/api/v1/approvals/${approvalId}`)
  await backend.post('bob', `/api/v1/approvals/${approvalId}/decisions`, { step: 0, verdict: 'approve', digest: asked.digest })
  await backend.waitForState(runId, ['succeeded'])
  const tickets = (await backend.tickets()).filter((ticket) => ticket.run_id === runId)
  expect(tickets, 'the practice Jira holds the ticket the test run wrote').toHaveLength(1)
  assertClean(watch)
  await context.close()
})

test('a release task goes to the Software watchlist, says why, and carries on as a new workflow with the task kept', async ({ browser }, info) => {
  const context = await devContext(browser, 'alice')
  const page = await context.newPage()
  await page.goto('/new')
  await planIt(page, RELEASE)
  await expect(page.getByRole('main')).toContainText('You mentioned “release”')
  await expect(page.getByRole('link', { name: 'Open Software watchlist' })).toHaveAttribute('href', '/software')
  await shot(page, info, 'p13-07-watchlist')
  await page.getByRole('button', { name: 'No, set it up as a new workflow' }).click()
  await expect(heading(page)).toHaveText(stepHeading(2, 'Check what I understood'))
  await expect(page.getByRole('main')).toContainText(RELEASE)
  await expect(page.getByRole('button', { name: 'Fill in' })).toHaveCount(4)
  await context.close()
})

test('a task with no schedule keeps Next off, and pressing it points at the missing row', async ({ browser }) => {
  const context = await devContext(browser, 'alice')
  const page = await context.newPage()
  await page.goto('/new')
  await planIt(page, NO_SCHEDULE)
  await expect(rowOf(page, 'When')).toContainText('please fill in')
  await expect(nextButton(page)).toHaveAttribute('aria-disabled', 'true')
  await expect(page.getByRole('main')).toContainText('Next opens when you say when it runs.')
  await pressNext(page)
  await expect(heading(page)).toHaveText(stepHeading(2, 'Check what I understood'))
  await expect(rowOf(page, 'When').getByRole('button', { name: 'Fill in' })).toBeFocused()
  await context.close()
})

test('a task that posts in Teams marks that part can’t do yet, and says why', async ({ browser }) => {
  const context = await devContext(browser, 'alice')
  const page = await context.newPage()
  await page.goto('/new')
  await planIt(page, TEAMS)
  await expect(rowOf(page, 'Where it goes')).toContainText('can’t do this yet')
  await expect(rowOf(page, 'Where it goes')).toContainText(/Teams/)
  await expect(nextButton(page)).toHaveAttribute('aria-disabled', 'true')
  await context.close()
})

test('a saved draft shows on Home and opens at the step it was saved at', async ({ browser }) => {
  const context = await devContext(browser, 'alice')
  const page = await context.newPage()
  await page.goto('/new')
  await planIt(page, FOLLOW_UP)
  const name = `p13 draft ${randomUUID().slice(0, 6)}`
  await fixRow(page, 'Does', `Create one follow-up ticket that lists them for ${name}`)
  await page.getByRole('button', { name: 'Save draft and close' }).click()
  await expect(page).toHaveURL(/\/$/)
  const drafts = page.getByRole('region', { name: 'Your drafts' })
  const row = drafts.getByRole('link').filter({ hasText: 'Step 2 of 4' }).first()
  await expect(row).toBeVisible()
  await row.click()
  await expect(heading(page)).toHaveText(stepHeading(2, 'Check what I understood'))
  await expect(rowOf(page, 'Does')).toContainText(name)
  await context.close()
})

test('bob has no New workflow in the menu, and the page says only Operators set up workflows', async ({ browser }) => {
  const context = await devContext(browser, 'bob')
  const page = await context.newPage()
  await page.goto('/')
  await expect(heading(page)).toBeVisible()
  await expect(page.getByRole('link', { name: 'New workflow' })).toHaveCount(0)
  await page.goto('/new')
  await expect(heading(page)).toHaveText('New workflow')
  await expect(page.getByRole('main')).toContainText('Only Operators set up workflows.')
  await context.close()
})

for (const phone of [false, true]) {
  const size = phone ? 'phone' : 'desktop'
  test(`each step has no WCAG 2.2 AA problem on the ${size}`, async ({ browser }) => {
    const context = await devContext(browser, 'alice', { phone })
    const page = await context.newPage()
    await page.goto('/new')
    await settled(page)
    await expectAccessible(page, path.join(OUT, 'axe'), `new-1-${size}`)
    await planIt(page, FOLLOW_UP)
    await expect(page.getByRole('region', { name: 'What the workflow will do' })).toContainText('Changes data, waits for a yes')
    await settled(page)
    await expectAccessible(page, path.join(OUT, 'axe'), `new-2-${size}`)
    await nextButton(page).click()
    await settled(page)
    await expectAccessible(page, path.join(OUT, 'axe'), `new-3-${size}`)
    await nextButton(page).click()
    await settled(page)
    await expectAccessible(page, path.join(OUT, 'axe'), `new-4-${size}`)
    await context.close()
  })
}
