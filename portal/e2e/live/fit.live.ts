import { randomUUID } from 'node:crypto'
import type { Page } from '@playwright/test'
import { CONTROL_KINDS, coverProblems, describeProblems, fitProblems, measure, seedControl, toggleProblems } from './support/fit'
import { connectMockModel } from './support/settings'
import { expect, test } from './support/test'
import { devContext } from './support/ui'

/**
 * The team lead's fit rule: no text spills out of or is cut off inside its card, box, button or pill, nothing overlaps,
 * buttons side by side line up, and no page scrolls sideways, from a narrow window to 1920 px.
 * Ported from the prototype's checks/fit.cjs (see support/fit.ts).
 */

test.beforeAll(async ({ baseURL }) => {
  await connectMockModel(String(baseURL))
})

/** One run waiting for a yes, started by the first test and visited by all. */
let runId: string | undefined

const WIDTHS = [1920, 1440, 1280, 1050, 1024, 901, 900, 768, 390] as const

/** A workflow that never ran, so a search for it leaves a Workflows list with no action in any row. */
let quiet: string | undefined

interface Screen {
  readonly name: string
  readonly path: string
  readonly heading: string | RegExp
  /** How it works is for Operators only. */
  readonly operatorOnly?: true
}

const ANY_HEADING = /\S/
const SCREENS: readonly Screen[] = [
  { name: 'Chat', path: '/', heading: ANY_HEADING },
  { name: 'Workflows', path: '/workflows', heading: 'Workflows' },
  { name: 'Watchlist', path: '/software', heading: 'Software watchlist' },
  { name: 'Settings, Connections', path: '/settings', heading: 'Settings' },
  { name: 'Settings, People and permissions', path: '/settings?tab=people', heading: 'Settings' },
  { name: 'Settings, AI model', path: '/settings?tab=model', heading: 'Settings' },
  { name: 'Settings, How it works', path: '/settings?tab=how', heading: 'Settings', operatorOnly: true },
  { name: 'Settings, How it works, Agents', path: '/settings?tab=how&show=agents', heading: 'Settings', operatorOnly: true },
  { name: 'Settings, How it works, Tools', path: '/settings?tab=how&show=tools', heading: 'Settings', operatorOnly: true },
  { name: 'Settings, How it works, an agent open', path: '/settings?tab=how&show=agents&agent=planner', heading: 'Settings', operatorOnly: true },
]

const USERS = [
  { id: 'alice', role: 'an Operator' },
  { id: 'bob', role: 'an Approver' },
] as const

async function settled(page: Page, screen: Screen): Promise<void> {
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  if (typeof screen.heading === 'string') await expect(page.getByRole('heading', { level: 1 })).toHaveText(screen.heading)
  await expect(page.getByRole('main').getByRole('status').filter({ hasText: /^Loading/ })).toHaveCount(0)
  if (screen.path === '/') {
    const main = page.getByRole('main')
    await expect(main.locator('[data-home-item]').or(main.getByText('All quiet', { exact: true })).or(main.locator('#planner-box')).first()).toBeVisible()
  }
  await page.waitForLoadState('networkidle', { timeout: 5_000 }).catch(() => undefined)
}

for (const user of USERS) {
  for (const width of WIDTHS) {
    test(`nothing spills, is cut off or overlaps, and the page does not scroll sideways, as ${user.role} at ${String(width)} px`, async ({ browser, backend }) => {
      runId ??= (await backend.waitingRun('alice')).runId
      if (quiet === undefined) {
        quiet = `Fit lane ${randomUUID().slice(0, 6)}`
        await backend.post('alice', '/api/v1/agent-use-cases', { name: quiet, instruction: 'Check LangGraph for a new release and raise a ticket in MOCK.', agents: [{ card_id: 'crd_version_checker', values: { 'GitHub repository': 'langchain-ai/langgraph', 'Jira project': 'MOCK' } }] }, undefined, [201])
      }
      const context = await devContext(browser, user.id, { reducedMotion: true })
      const page = await context.newPage()
      await page.setViewportSize({ width, height: width > 900 ? 1000 : 844 })
      const found: string[] = []
      const runPage: Screen = { name: 'A run waiting for a yes', path: `/runs/${runId}`, heading: ANY_HEADING }
      for (const screen of [...SCREENS, runPage].filter((s) => user.id === 'alice' || s.operatorOnly !== true)) {
        await page.goto(screen.path)
        await settled(page, screen)
        const problems = await fitProblems(page)
        if (problems.length) found.push(`${screen.name} (${screen.path}) at ${String(width)} px as ${user.role}:\n${describeProblems(problems).replace(/^/gm, '    ')}`)
      }
      await page.goto('/workflows')
      await settled(page, { name: 'Workflows', path: '/workflows', heading: 'Workflows' })
      await page.getByRole('button', { name: 'Search workflows' }).click()
      await page.getByRole('searchbox', { name: 'Find a workflow' }).fill(quiet)
      await expect(page.getByRole('list', { name: 'Workflows' }).locator('li[data-workflow-id]')).toHaveCount(1)
      const noAction = await fitProblems(page)
      if (noAction.length) found.push(`Workflows with no action in any row at ${String(width)} px as ${user.role}:\n${describeProblems(noAction).replace(/^/gm, '    ')}`)
      await context.close()
      expect(found, found.join('\n')).toEqual([])
    })
  }
}

test('the check can fail: a seeded overflow, a clipped label, an overlap, two unequal buttons, a part-covered button and a toggle on the product are all caught', async ({ browser }) => {
  const context = await devContext(browser, 'alice', { reducedMotion: true })
  const page = await context.newPage()
  await page.goto('/workflows')
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  await page.evaluate(seedControl)
  const kinds = new Set([...(await page.evaluate(measure)), ...(await page.evaluate(coverProblems)), ...(await page.evaluate(toggleProblems))].map((p) => p.kind))
  expect([...kinds].sort(), 'the check names each seeded problem').toEqual(expect.arrayContaining([...CONTROL_KINDS].sort()))
  await context.close()
})
