import path from 'node:path'
import type { Page } from '@playwright/test'
import { expectAccessible } from '../support/axe'
import { assertClean, watchPage } from '../support/test'
import { expect, test } from './support/test'
import { connectMockModel } from './support/settings'
import { devContext, needsOnWorkflows, OUT, shot } from './support/ui'

test.beforeAll(async ({ baseURL }) => {
  await connectMockModel(String(baseURL))
})

const needsYou = (page: Page) => page.getByRole('list', { name: 'Needs you' })
const itemOf = (page: Page, approvalId: string) => page.locator(`li[data-home-item="approval:${approvalId}"]`)
const waitingOnOthers = (page: Page) => page.getByRole('region', { name: 'Waiting on others' })

async function markThisPage(page: Page): Promise<void> {
  await page.evaluate(() => {
    ;(window as unknown as { __homeNotReloaded: boolean }).__homeNotReloaded = true
  })
}

async function notReloaded(page: Page): Promise<boolean> {
  return page.evaluate(() => (window as unknown as { __homeNotReloaded?: boolean }).__homeNotReloaded === true)
}

test('bob sees the run alice started at the top of Home, and its row opens the run at the decision', async ({ browser, backend }, info) => {
  const { runId, approvalId } = await backend.waitingRun('alice')
  const context = await devContext(browser, 'bob')
  const page = await context.newPage()
  const watch = watchPage(page)
  await page.goto('/')
  const first = needsYou(page).locator('li[data-home-item]').first()
  await expect(first).toHaveAttribute('data-home-item', `approval:${approvalId}`)
  await expect(first).toContainText(/needs your approval/)
  await expect(first.getByRole('link')).toHaveCount(1)
  await expect(first.getByRole('link')).toHaveAttribute('href', `/runs/${runId}`)
  await expect(page.getByRole('main').getByRole('button', { name: /^Approve/ }), 'nothing is decided on Home').toHaveCount(0)
  await shot(page, info, 'p11-06-bob-home')

  await first.getByRole('link').click()
  await expect(page).toHaveURL(new RegExp(`/runs/${runId}$`))
  await expect(page.locator('#decision'), 'the run page lands on the decision').toBeFocused()
  await expect(page.getByRole('button', { name: 'Approve', exact: true })).toBeVisible()
  assertClean(watch)
  await context.close()
})

test('Home’s board lists the workflows as tiles under Needs you, each one link with its one pill, and a workflow that needs Bob says why only in Needs you', async ({ browser, backend }, info) => {
  const { approvalId } = await backend.waitingRun('alice')
  const context = await devContext(browser, 'bob')
  const page = await context.newPage()
  await page.goto('/')
  await expect(itemOf(page, approvalId)).toBeVisible()
  const board = page.locator('ul[data-board]')
  const tile = board.locator('li[data-workflow-id]').filter({ hasText: 'Software watchlist' })
  await expect(tile.getByRole('link')).toHaveAttribute('href', /^\/workflows\/.+/)
  await expect(tile, 'its one pill is Needs you').toContainText('Needs you')
  await expect(tile, 'the reason is in Needs you, not on the tile').not.toContainText('needs your approval')
  await expect(board.getByText('needs your approval'), 'no tile says it').toHaveCount(0)
  await expect(itemOf(page, approvalId), 'Needs you says it once').toHaveCount(1)
  const edges = await page.evaluate(() => ['form', 'ul[aria-label="Needs you"]', 'ul[data-board]'].map((query) => document.querySelector(query)?.getBoundingClientRect().left ?? -1))
  expect(Math.max(...edges) - Math.min(...edges), 'the box, Needs you and the board start at one left edge').toBeLessThanOrEqual(1)
  for (const width of [1280, 800]) {
    await page.setViewportSize({ width, height: 900 })
    const fit = await page.evaluate(() => {
      const tiles = [...document.querySelectorAll('ul[data-board] > li[data-workflow-id]')]
      const pills = tiles.flatMap((item) => [...item.querySelectorAll('[data-life]')]).map((pill) => pill.getBoundingClientRect().height)
      const lines = tiles.flatMap((item) => {
        const line = item.querySelector('[role="img"]')
        return line ? [{ row: Math.round(item.getBoundingClientRect().top), inTile: Math.round(line.getBoundingClientRect().top - item.getBoundingClientRect().top) }] : []
      })
      return { tallest: Math.max(0, ...pills), lines }
    })
    expect(fit.tallest, `every board pill is one line at ${String(width)} px`).toBeLessThan(34)
    for (const row of new Set(fit.lines.map((line) => line.row))) {
      const heights = new Set(fit.lines.filter((line) => line.row === row).map((line) => line.inTile))
      expect(heights.size, `step lines in one row share a top edge at ${String(width)} px`).toBe(1)
    }
  }
  const spacing = await page.evaluate(() => {
    const top = (query: string) => document.querySelector(query)?.getBoundingClientRect().top ?? -1
    const bottom = (query: string) => document.querySelector(query)?.getBoundingClientRect().bottom ?? -1
    const needsHead = bottom('section[aria-labelledby] > h2')
    const boardHead = bottom('section:has(ul[data-board]) h2')
    const groups = [...document.querySelectorAll('ul[aria-label="Needs you"] > li > h3')]
    const firstList = document.querySelector('ul[aria-label="Needs you"] > li > ul')
    const rows = [...document.querySelectorAll('ul[aria-label="Needs you"] li[data-home-item]')].map((row) => row.getBoundingClientRect())
    const across = rows.find((row, index) => index > 0 && row.top === rows[0]?.top)
    return {
      needsGap: top('ul[aria-label="Needs you"]') - needsHead,
      boardGap: top('ul[data-board]') - boardHead,
      headToList: (firstList?.getBoundingClientRect().top ?? 0) - (groups[0]?.getBoundingClientRect().bottom ?? 0),
      tileGap: across && rows[0] ? across.left - rows[0].right : 16,
    }
  })
  expect(spacing.boardGap, 'the Needs you heading sits as far above its list as the board’s does above its own').toBeGreaterThan(0)
  expect(Math.abs(spacing.needsGap - spacing.boardGap), 'heading to list is equal for Needs you and the board').toBeLessThanOrEqual(1)
  expect(spacing.tileGap, 'tiles are 16 px apart').toBeGreaterThan(0)
  await shot(page, info, 'mc-board-bob-home')
  await context.close()
})

test('alice sees no Waiting on others on Home or Workflows, and the run she started reads On, waiting for an Approver’s yes, on its workflow’s row', async ({ browser, backend }, info) => {
  const { runId, approvalId } = await backend.waitingRun('alice')
  const context = await devContext(browser, 'alice')
  const page = await context.newPage()
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  await expect(waitingOnOthers(page)).toHaveCount(0)
  await expect(itemOf(page, approvalId)).toHaveCount(0)
  await expect(page.getByRole('button', { name: /^Approve/ })).toHaveCount(0)
  await shot(page, info, 'p11-06-alice-home')
  await page.goto('/workflows')
  await expect(page.locator('li[data-workflow-id]').filter({ hasText: 'Software watchlist' })).toContainText('On · waiting for approval')
  const pill = page.locator('li[data-workflow-id]').filter({ hasText: 'Software watchlist' }).locator('[data-life]')
  expect((await pill.boundingBox())?.height ?? 99, 'the state column fits its longest pill on one line').toBeLessThan(34)
  await expect(waitingOnOthers(page)).toHaveCount(0)
  await expect(page.locator(`a[href="/runs/${runId}"]`), 'Needs you offers alice no run she can’t decide').toHaveCount(0)
  await context.close()
})

test('bob approves on the run page, and the item has left Home when he comes back, without a reload', async ({ browser, backend }) => {
  const { approvalId } = await backend.waitingRun('alice')
  const context = await devContext(browser, 'bob')
  const page = await context.newPage()
  await page.goto('/')
  await expect(itemOf(page, approvalId)).toBeVisible()
  await markThisPage(page)
  await itemOf(page, approvalId).getByRole('link').click()
  await page.getByRole('button', { name: 'Approve', exact: true }).click()
  await expect(page.locator('[data-run-pill]', { hasText: /^(Approved by Bob|Done)$/ })).toBeVisible()
  await page.getByRole('navigation', { name: 'Browse' }).filter({ visible: true }).getByRole('link', { name: /^Home/ }).click()
  await expect(page.locator('#planner-box')).toBeVisible()
  await expect(itemOf(page, approvalId)).toHaveCount(0)
  expect(await notReloaded(page), 'Home updated without a reload').toBe(true)
  await context.close()
})

test('a yes from the Teams card’s link takes the item off Home at once, without a reload', async ({ browser, backend }, info) => {
  const { approvalId } = await backend.waitingRun('alice')
  const context = await devContext(browser, 'bob')
  const page = await context.newPage()
  await page.goto('/')
  await expect(itemOf(page, approvalId)).toBeVisible()
  await markThisPage(page)
  await page.getByRole('button', { name: /^Teams, practice copy/ }).click()
  const message = page.getByRole('dialog', { name: 'Teams, practice copy' }).locator(`li[data-approval-id="${approvalId}"]`)
  await message.scrollIntoViewIfNeeded()
  // The card's link opens the approval page, and Bob decides there. The drawer closes first, so its own Approve is not in the way.
  await message.getByRole('link', { name: 'Open in AI Workflow Builder' }).click()
  await expect(page.getByRole('dialog', { name: 'Teams, practice copy' })).toBeHidden()
  await page.locator('#decision').getByRole('button', { name: 'Approve', exact: true }).click()
  await page.getByRole('navigation', { name: 'Browse' }).getByRole('link', { name: /^Home/ }).click()
  await expect(itemOf(page, approvalId)).toHaveCount(0, { timeout: 15_000 })
  await page.getByRole('button', { name: /^Teams, practice copy/ }).click()
  await expect(message).toContainText('Approved by Bob', { timeout: 30_000 })
  await page.keyboard.press('Escape')
  expect(await notReloaded(page), 'Home updated without a reload').toBe(true)
  await shot(page, info, 'p11-06-after-teams-yes')
  await context.close()
})

test('what needs an Approver is one number on Home, on Home in the rail and on Workflows, and the rail shows totals beside it (principle 7)', async ({ browser, backend }) => {
  const { approvalId } = await backend.waitingRun('alice')
  const context = await devContext(browser, 'bob')
  const page = await context.newPage()
  const menu = page.getByRole('navigation', { name: 'Browse' }).filter({ visible: true })
  await page.goto('/')
  await expect(itemOf(page, approvalId)).toBeVisible()
  const onHome = Number((await page.getByRole('heading', { level: 1 }).innerText()).replace(/\D/g, ''))
  expect(onHome, 'his Home’s heading counts what needs him').toBeGreaterThan(0)
  await expect(menu.getByRole('link', { name: `Home, ${onHome === 1 ? '1 thing needs' : `${String(onHome)} things need`} you` }), 'Home in the rail carries the same count').toBeVisible()
  await expect(menu.getByRole('link', { name: /^Workflows, \d+ in all$/ }), 'Workflows counts the team’s workflows').toBeVisible()

  await menu.getByRole('link', { name: /^Workflows/ }).click()
  await expect(page).toHaveURL(/\/workflows$/)
  expect(await needsOnWorkflows(page), 'his heading is the Needs you rows on Workflows, every one reached with Show more').toBe(onHome)
  await context.close()
})

for (const phone of [false, true]) {
  test(`Home passes WCAG 2.2 AA and does not scroll sideways at ${phone ? '390' : '1440'} px`, async ({ browser, backend }) => {
    await backend.waitingRun('alice')
    const context = await devContext(browser, 'bob', { phone })
    const page = await context.newPage()
    await page.goto('/')
    await expect(needsYou(page)).toBeVisible()
    await page.waitForFunction(() => document.getAnimations().length === 0)
    await expectAccessible(page, path.join(OUT, 'axe'), `home-bob-${phone ? 'phone' : 'desktop'}`)
    const widths = await page.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth])
    expect(widths[0], 'no sideways scroll').toBeLessThanOrEqual(widths[1] ?? 0)
    await context.close()
  })
}
