import type { Page } from '@playwright/test'
import { assertClean, watchPage } from '../support/test'
import { expect, test } from './support/test'
import { devContext, shot } from './support/ui'

interface ApprovalAnswer {
  actions: { fields: { title: string } }[]
  you_can_decide: boolean
  why_not: string | null
}

const heading = (page: Page) => page.getByRole('heading', { level: 1 })
const steps = (page: Page) => page.getByRole('list', { name: 'Steps of this run' }).locator('li[data-state]')

test('alice starts a check; bob opens the waiting run, sees the ticket it will create, approves, and watches it reach Done', async ({ browser, backend }, info) => {
  const { runId, approvalId } = await backend.waitingRun('alice')
  const forBob = await backend.get<ApprovalAnswer>('bob', `/api/v1/approvals/${approvalId}`)
  expect(forBob.you_can_decide, 'the platform lets bob decide').toBe(true)
  const title = forBob.actions[0]?.fields.title ?? ''
  expect(title).toContain('LangGraph')

  const aliceContext = await devContext(browser, 'alice')
  const alice = await aliceContext.newPage()
  const aliceWatch = watchPage(alice)
  await alice.goto(`/runs/${runId}`)
  await expect(heading(alice)).toHaveText('1 ticket is waiting for a yes')
  await expect(alice.locator('#decision'), 'opening a waiting run lands on the decision').toBeFocused()
  await expect(alice.getByRole('main')).toContainText(title)
  await expect(alice.getByRole('main')).toContainText('You started this run, so you can’t approve it. Nobody approves their own work.')
  await expect(alice.getByRole('button', { name: /^Approve/ })).toHaveCount(0)
  await shot(alice, info, 'p5-02-alice-own-run')
  assertClean(aliceWatch)
  await aliceContext.close()

  const bobContext = await devContext(browser, 'bob')
  const bob = await bobContext.newPage()
  const bobWatch = watchPage(bob)
  await bob.goto(`/runs/${runId}`)
  await expect(heading(bob)).toHaveText('1 ticket is waiting for a yes')
  await expect(bob.locator('#decision')).toBeFocused()
  const main = bob.getByRole('main')
  await expect(main).toContainText('1 ticket will be created in Jira project MOCK')
  await expect(main).toContainText(title)
  await expect(main).toContainText('This is exactly what will be written, and nothing else.')
  await expect(bob.locator('li[aria-current="step"]')).toContainText('Waiting for a yes')
  await shot(bob, info, 'p5-02-bob-waiting')

  const ticketsBefore = (await backend.tickets()).filter((ticket) => ticket.run_id === runId)
  expect(ticketsBefore, 'nothing is written before the yes').toEqual([])
  await bob.getByRole('button', { name: 'Approve 1 ticket' }).click()

  await expect(heading(bob)).toHaveText('1 ticket created in Jira', { timeout: 60_000 })
  await expect(steps(bob)).toHaveCount(6)
  for (const step of await steps(bob).all()) await expect(step).toHaveAttribute('data-state', 'done')
  await expect(steps(bob).last()).toContainText('Done: Done')
  await expect(bob.locator('[data-gate-said]').last(), 'after the yes, focus moves to what the gate said').toBeFocused()
  await expect(bob.locator('[data-gate-said]').last()).toHaveText('Bob approved.')

  const written = (await backend.tickets()).filter((ticket) => ticket.run_id === runId)
  expect(written.map((ticket) => ticket.title)).toEqual([title])
  await expect(main).toContainText(`Created ${written[0]?.key ?? ''} in Jira.`)
  await expect(main).toContainText('Bob approved, and the platform created the ticket.')
  expect((await backend.run(runId)).state).toBe('succeeded')
  await shot(bob, info, 'p5-02-bob-done')
  assertClean(bobWatch)
  await bobContext.close()
})

test('the link in a Teams message opens the run page at the decision', async ({ browser, backend }, info) => {
  const { runId, approvalId } = await backend.waitingRun('alice')
  const message = (await backend.teamsMessages()).find((item) => item.approval_id === approvalId)
  expect(message?.link).toBe(`/approvals/${approvalId}`)

  const context = await devContext(browser, 'bob')
  const page = await context.newPage()
  const watch = watchPage(page)
  await page.goto('/')
  const teams = page.getByRole('button', { name: /^Teams, practice copy, \d+ approvals? waiting for you$/ })
  await expect(teams, 'the Teams button counts what waits for bob').toBeVisible({ timeout: 15_000 })
  await teams.click()
  const drawer = page.getByRole('dialog', { name: 'Teams, practice copy' })
  const card = drawer.locator(`li[data-approval-id="${approvalId}"]`)
  await expect(card.getByRole('button', { name: 'Approve' })).toBeVisible()
  await shot(page, info, 'p5-02-teams-drawer')
  await card.getByRole('link', { name: 'Open in Workflow Builder' }).click()
  await expect(page).toHaveURL(new RegExp(`/approvals/${approvalId}$`))
  await expect(drawer).toBeHidden()
  await expect(page.locator('#decision')).toBeFocused()
  await expect(page.getByRole('button', { name: 'Approve 1 ticket' })).toBeVisible()

  await page.getByRole('button', { name: 'Decline' }).click()
  await expect(heading(page)).toHaveText('Declined, nothing was written', { timeout: 60_000 })
  await expect(page.getByRole('main')).toContainText('Bob declined, so nothing was written.')
  expect((await backend.tickets()).filter((ticket) => ticket.run_id === runId)).toEqual([])
  assertClean(watch)
  await context.close()
})
