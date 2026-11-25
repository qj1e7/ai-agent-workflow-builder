import path from 'node:path'
import { randomUUID } from 'node:crypto'
import type { Locator, Page } from '@playwright/test'
import { expectAccessible } from '../support/axe'
import { assertClean, watchPage } from '../support/test'
import type { Backend } from './support/stack'
import { expect, test } from './support/test'
import { devContext, OUT, shot } from './support/ui'

// ENGINE-PLAN E8: the In n8n tabs, for people with n8n access only. The sketch's "Alice, with n8n access" is Carol here: the
// stack's Alice is an Approver too, and an Approver can never hold n8n access. Alice gives Carol n8n access for this file and
// takes it away again at the end, so no other spec meets a Carol who has it.

const AGENTS = [{ card_id: 'crd_version_checker', values: { 'GitHub repository': 'langchain-ai/langgraph', 'Jira project': 'MOCK' } }]
const SAFE_BLOCKS = 'Only our blocks and n8n’s safe ones are on, so every write waits for a yes.'

const views = (page: Page): Locator => page.getByRole('main').getByRole('group', { name: 'View' })
const canvasTitle = (page: Page): Locator => page.getByRole('main').locator('svg title').first()

async function n8nAccess(backend: Backend, on: boolean): Promise<void> {
  const answer = await backend.send('PUT', 'alice', '/api/v1/people/carol/n8n-access', { n8n_access: on })
  expect(answer.status, `Alice ${on ? 'gives Carol' : 'takes away Carol’s'} n8n access: ${JSON.stringify(answer.body)}`).toBe(200)
}

async function noSideways(page: Page): Promise<void> {
  const over = await page.evaluate(() => document.scrollingElement!.scrollWidth - document.scrollingElement!.clientWidth)
  expect(over, 'nothing wider than the window; the canvas scrolls inside its own box').toBeLessThanOrEqual(0)
}

test.describe('the In n8n tabs', () => {
  let useCaseId = ''
  let runId = ''

  test.beforeAll(async ({ backend }) => {
    useCaseId = (await backend.post<{ use_case_id: string }>('alice', '/api/v1/agent-use-cases', { name: `In n8n ${randomUUID().slice(0, 6)}`, instruction: 'Check LangGraph for a new release and raise a ticket in MOCK.', agents: AGENTS }, undefined, [201])).use_case_id
    runId = (await backend.waitingRun('alice')).runId
    await n8nAccess(backend, true)
  })

  test.afterAll(async ({ backend }) => {
    await n8nAccess(backend, false)
    await backend.delete('alice', `/api/v1/use-cases/${useCaseId}`, [200, 404])
    const check = (await backend.run(runId)).use_case_id
    await backend.declineWaitingChecks(check)
  })

  test('an Operator with n8n access sees Summary and In n8n on the workflow, with its canvas and what she may do in n8n', async ({ browser }, info) => {
    const context = await devContext(browser, 'carol')
    const page = await context.newPage()
    const watch = watchPage(page)
    await page.goto(`/workflows/${useCaseId}`)
    await expect(page.getByRole('banner')).toContainText('Carol, Operator, n8n access')
    await expect(views(page).getByRole('button')).toHaveText(['Summary', 'In n8n'])
    await expect(views(page).getByRole('button', { name: 'Summary' })).toHaveAttribute('aria-pressed', 'true')

    await views(page).getByRole('button', { name: 'In n8n' }).focus()
    await page.keyboard.press('Enter')
    await expect(page, 'the tab is in the address, so a reload keeps it').toHaveURL(new RegExp(`/workflows/${useCaseId}\\?view=n8n$`))
    const main = page.getByRole('main')
    await expect(main).toContainText(/Version 1, (published|saved as a draft) by Alice, /)
    await expect(main).toContainText(SAFE_BLOCKS)
    await expect(canvasTitle(page)).toHaveText(/ in n8n: .*Ask for approval/)
    const open = main.getByRole('button', { name: /^Open in n8n editor/ })
    const why = main.getByText(/Set your n8n password first|n8n account isn’t made yet|n8n account isn't made yet|Turn it on first/)
    await expect(open.or(why).first(), 'Open in n8n editor, or the reason it can’t open yet, never a dead button').toBeVisible()
    await expect(main.locator(':is(button, input, select, textarea):disabled, [aria-disabled="true"]')).toHaveCount(0)
    await expectAccessible(page, path.join(OUT, 'axe'), 'e8-workflow-in-n8n')
    await shot(page, info, 'e8-workflow-in-n8n-carol')

    await page.reload()
    await expect(views(page).getByRole('button', { name: 'In n8n' })).toHaveAttribute('aria-pressed', 'true')
    assertClean(watch)
    await context.close()
  })

  test('she sees the run on its canvas, each block in the run’s state, waiting at the yes', async ({ browser }, info) => {
    const context = await devContext(browser, 'carol')
    const page = await context.newPage()
    await page.goto(`/runs/${runId}`)
    await expect(views(page).getByRole('button')).toHaveText(['Steps', 'In n8n'])
    await views(page).getByRole('button', { name: 'In n8n' }).click()
    await expect(canvasTitle(page)).toHaveText(/Ask for approval \(waiting\)/)
    await expect(canvasTitle(page)).toHaveText(/\(done\)/)
    await expectAccessible(page, path.join(OUT, 'axe'), 'e8-run-in-n8n')
    await shot(page, info, 'e8-run-in-n8n-carol')
    await context.close()
  })

  test('Bob, an Approver, sees neither tab, and the address can’t open one for him; nor does Alice, who has no n8n access', async ({ browser }, info) => {
    const context = await devContext(browser, 'bob')
    const page = await context.newPage()
    await page.goto(`/workflows/${useCaseId}?view=n8n`)
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
    await expect(views(page)).toHaveCount(0)
    await expect(page.getByRole('main')).not.toContainText(SAFE_BLOCKS)
    await shot(page, info, 'e8-workflow-bob')
    await page.goto(`/runs/${runId}?view=n8n`)
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
    await expect(views(page)).toHaveCount(0)
    await expect(page.getByRole('main').locator('svg title')).toHaveCount(0)
    await context.close()
    const alice = await devContext(browser, 'alice')
    const hers = await alice.newPage()
    await hers.goto(`/workflows/${useCaseId}`)
    await expect(hers.getByRole('heading', { level: 1 })).toBeVisible()
    await expect(views(hers)).toHaveCount(0)
    await expect(hers.getByRole('main').getByRole('button', { name: /^Open in n8n editor/ })).toHaveCount(0)
    await alice.close()
  })

  test('at 390 px wide nothing spills sideways, and with reduced motion the canvas changes state without moving', async ({ browser }, info) => {
    const narrow = await devContext(browser, 'carol', { phone: true, reducedMotion: true })
    const page = await narrow.newPage()
    for (const at of [`/workflows/${useCaseId}?view=n8n`, `/runs/${runId}?view=n8n`]) {
      await page.goto(at)
      await expect(canvasTitle(page)).toBeAttached()
      await noSideways(page)
      const node = page.getByRole('main').locator('svg g[data-state][transform]').first()
      expect(await node.evaluate((el) => getComputedStyle(el).transitionDuration), 'reduced motion stops the state changes moving').toBe('0s')
    }
    await shot(page, info, 'e8-run-in-n8n-390')
    await narrow.close()
  })
})
