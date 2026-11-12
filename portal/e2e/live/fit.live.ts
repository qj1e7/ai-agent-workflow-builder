import { randomUUID } from 'node:crypto'
import path from 'node:path'
import type { Locator, Page } from '@playwright/test'
import { expectAccessible } from '../support/axe'
import { CONTROL_KINDS, coverProblems, describeProblems, fitProblems, measure, seedControl, toggleProblems } from './support/fit'
import { holdRunAtWork, runLinks } from './support/runLine'
import { connectMockModel } from './support/settings'
import { setMockGithubMode, type Backend } from './support/stack'
import { expect, test } from './support/test'
import { devContext, OUT, shot } from './support/ui'

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
  /** The line under the title that comes from the page's data, measured once it is there. */
  readonly lead?: RegExp
  /** How it works is for Operators only. */
  readonly operatorOnly?: true
}

const ANY_HEADING = /\S/
const SCREENS: readonly Screen[] = [
  { name: 'Chat', path: '/', heading: ANY_HEADING },
  { name: 'Workflows', path: '/workflows', heading: 'Workflows' },
  { name: 'Watchlist', path: '/software', heading: 'Software watchlist', lead: /^(?:\d+ (?:has|have) a newer version(?: · \d+ can’t be checked)?(?: · \d+ not checked yet)?|\d+ can’t be checked(?: · \d+ not checked yet)?|\d+ not checked yet|Everything is up to date\.|Nothing newer yet\.|Everything your team runs, in one list\.)$/ },
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
  if (screen.lead) await expect(page.locator('main h1 + p'), `${screen.name}'s count line`).toHaveText(screen.lead)
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

for (const width of WIDTHS) {
  test(`the chat with the docked box and the pinned line fits, and the box stays on screen, as an Operator at ${String(width)} px`, async ({ browser, backend }) => {
    const answering = (on: boolean) => backend.post('alice', '/api/v1/dev/practice-jira/answering', { answering: on })
    await answering(false)
    await backend.post('alice', '/api/v1/settings/connections/jira/check')
    const context = await devContext(browser, 'alice', { reducedMotion: true })
    const page = await context.newPage()
    const height = width > 900 ? 1000 : 844
    await page.setViewportSize({ width, height })
    try {
      await page.goto('/')
      const box = page.getByLabel('Ask the Planner about software versions')
      await box.fill('Check my workflows')
      await box.press('Enter')
      await expect(page.getByRole('region', { name: 'Most urgent' })).toBeVisible()
      await expect(page.getByRole('list', { name: 'Your workflows' }).first()).toBeVisible()
      await page.waitForLoadState('networkidle', { timeout: 5_000 }).catch(() => undefined)
      const problems = await fitProblems(page)
      expect(problems.length ? describeProblems(problems) : '', `the chat at ${String(width)} px`).toBe('')
      const docked = await box.boundingBox()
      expect(docked && docked.y + docked.height <= height, 'the box is docked inside the window').toBe(true)
    } finally {
      await answering(true)
      await backend.post('alice', '/api/v1/settings/connections/jira/check')
      await context.close()
    }
  })
}

/** What the side panel's views need: a workflow that never ran, a run that stopped, and a run Carol started that Alice may decide. */
interface PanelFacts {
  readonly workflow: string
  readonly stopped: { readonly name: string; readonly runId: string }
  readonly request: string
}

let panelFacts: PanelFacts | undefined

const AGENTS = [{ card_id: 'crd_version_checker', values: { 'GitHub repository': 'langchain-ai/langgraph', 'Jira project': 'MOCK' } }]

async function agentWorkflow(backend: Backend, user: string, name: string): Promise<string> {
  const made = await backend.post<{ use_case_id: string }>(user, '/api/v1/agent-use-cases', { name, instruction: 'Check LangGraph for a new release and raise a ticket in MOCK.', agents: AGENTS }, undefined, [201])
  return made.use_case_id
}

async function panelSetup(backend: Backend): Promise<PanelFacts> {
  const tag = randomUUID().slice(0, 6)
  const workflow = `Fit panel ${tag}`
  const stoppedName = `Fit stops ${tag}`
  await agentWorkflow(backend, 'alice', workflow)
  const stoppedId = await agentWorkflow(backend, 'alice', stoppedName)
  let stopped = ''
  try {
    await setMockGithubMode('unavailable')
    stopped = await backend.checkNow('alice', stoppedId)
    await backend.waitForState(stopped, ['failed'], 150_000)
  } finally {
    await setMockGithubMode('ok')
  }
  const request = await backend.checkNow('carol', await agentWorkflow(backend, 'carol', `Fit request ${tag}`))
  await backend.waitForState(request, ['awaiting_approval'])
  await backend.freshWatchlist('alice')
  return { workflow, stopped: { name: stoppedName, runId: stopped }, request }
}

const SHOT_WIDTHS: ReadonlySet<number> = new Set([1920, 1280, 1050, 900, 390])

/**
 * The side panel beside the chat at 1920 to 901 px and over the whole window at 900 px and narrower, with each of its views:
 * a workflow, a request to decide, a stopped run and a software. Only an Operator has a chat to open it from until the Planner's
 * box opens to Approvers (R16), so Bob is not drawn here.
 */
for (const width of [1920, 1440, 1280, 1050, 901, 900, 390] as const) {
  test(`the side panel and each of its views fit beside the chat, or over the window at 900 px and narrower, as an Operator at ${String(width)} px`, async ({ browser, backend }, info) => {
    test.slow()
    panelFacts ??= await panelSetup(backend)
    const facts = panelFacts
    const context = await devContext(browser, 'alice', { reducedMotion: true })
    const page = await context.newPage()
    await page.setViewportSize({ width, height: width > 900 ? 1000 : 844 })
    const box = page.getByLabel('Ask the Planner about software versions')
    const newest = page.getByRole('list', { name: 'Conversation with the Planner' }).locator(':scope > li').last()
    const panel = page.locator('#side-panel')
    const views: readonly (readonly [string, string, () => Locator, () => Locator])[] = [
      ['workflow', 'Check my workflows', () => newest.getByRole('button', { name: facts.workflow, exact: true }), () => panel.getByText('Next run')],
      ['approval', 'What needs me?', () => newest.locator(`[data-opens="run:${facts.request}"]`), () => panel.getByRole('button', { name: 'Decline' })],
      ['run', `Why did ${facts.stopped.name} stop?`, () => newest.locator(`[data-opens="run:${facts.stopped.runId}"]`), () => panel.getByText('Safe to retry')],
      ['software', 'Monitor LangGraph releases', () => newest.getByRole('button', { name: 'Open it' }), () => panel.getByText('Checked by')],
    ]
    const found: string[] = []
    try {
      await page.goto('/')
      for (const [view, words, opener, ready] of views) {
        await box.fill(words)
        await box.press('Enter')
        await expect(newest).toHaveAttribute('data-answer', 'true')
        await opener().click()
        await expect(ready()).toBeVisible({ timeout: 20_000 })
        await expect(panel).toHaveAttribute('role', width > 900 ? 'complementary' : 'dialog')
        await page.waitForLoadState('networkidle', { timeout: 5_000 }).catch(() => undefined)
        // The shot comes first, because the cover check scrolls each control into view.
        if (SHOT_WIDTHS.has(width)) await shot(page, info, `r3-panel-${view}-alice-${String(width)}`)
        const problems = await fitProblems(page)
        if (problems.length) found.push(`The side panel's ${view} view at ${String(width)} px:\n${describeProblems(problems).replace(/^/gm, '    ')}`)
        if (width === 1280 || width === 900) await expectAccessible(page, path.join(OUT, 'axe'), `side-panel-${view}-${String(width)}`)
        await panel.getByRole('button', { name: 'Close' }).click()
        await expect(panel).toHaveCount(0)
      }
    } finally {
      await context.close()
    }
    expect(found, found.join('\n')).toEqual([])
  })
}

/** Runs for each state the run line shows: one waiting for a yes, which is also held back to show it at work, one done and one stopped. */
interface LineRuns {
  readonly waiting: string
  readonly done: string
  readonly stopped: string
}

let lineRuns: LineRuns | undefined

async function approve(backend: Backend, runId: string): Promise<void> {
  const approvalId = await backend.approvalIdOf(runId)
  const { digest } = await backend.get<{ digest: string }>('bob', `/api/v1/approvals/${approvalId}`)
  await backend.post('bob', `/api/v1/approvals/${approvalId}/decisions`, { step: 0, verdict: 'approve', digest })
}

async function lineSetup(backend: Backend): Promise<LineRuns> {
  const facts = (panelFacts ??= await panelSetup(backend))
  const tag = randomUUID().slice(0, 6)
  const waiting = await backend.checkNow('alice', await agentWorkflow(backend, 'alice', `Fit waits ${tag}`))
  const done = await backend.checkNow('alice', await agentWorkflow(backend, 'alice', `Fit done ${tag}`))
  await backend.waitForState(waiting, ['awaiting_approval'])
  await backend.waitForState(done, ['awaiting_approval'])
  await approve(backend, done)
  await backend.waitForState(done, ['succeeded'])
  return { waiting, done, stopped: facts.stopped.runId }
}

const LINE_STATES = {
  'at-work': /^solid( solid)* flow( todo)+$/,
  waiting: /^solid( solid)* wait( todo)+$/,
  stopped: /^solid( solid)* stop( todo)*$/,
  done: /^solid( solid)*$/,
} as const

const LINE_SHOT_WIDTHS: ReadonlySet<number> = new Set([1920, 1280, 900, 390])

for (const width of WIDTHS) {
  test(`the run line fits at work, waiting for a yes, stopped and done, with each link in its state, as an Operator at ${String(width)} px`, async ({ browser, backend }, info) => {
    test.slow()
    lineRuns ??= await lineSetup(backend)
    const runs = lineRuns
    const context = await devContext(browser, 'alice', { reducedMotion: true })
    const page = await context.newPage()
    await page.setViewportSize({ width, height: width > 900 ? 1000 : 844 })
    const found: string[] = []
    try {
      for (const [state, runId] of [['at-work', runs.waiting], ['waiting', runs.waiting], ['stopped', runs.stopped], ['done', runs.done]] as const) {
        if (state === 'at-work') await holdRunAtWork(page, runId)
        await page.goto(`/runs/${runId}`)
        await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
        await expect.poll(async () => (await runLinks(page)).join(' '), { message: `the run line ${state} at ${String(width)} px` }).toMatch(LINE_STATES[state])
        await page.waitForLoadState('networkidle', { timeout: 5_000 }).catch(() => undefined)
        if (LINE_SHOT_WIDTHS.has(width)) await shot(page, info, `r11-run-${state}-alice-${String(width)}`)
        const problems = await fitProblems(page)
        if (problems.length) found.push(`The run page ${state} at ${String(width)} px:\n${describeProblems(problems).replace(/^/gm, '    ')}`)
        if (state === 'at-work') await page.unrouteAll({ behavior: 'ignoreErrors' })
      }
    } finally {
      await context.close()
    }
    expect(found, found.join('\n')).toEqual([])
  })
}

/**
 * The side panel's run line is the run page's line, small and without faces (RUN-line-panel). It shows one run held back to
 * when its agent was at work, then follows it from its stop, through a retry pressed in the panel, to its yes and to done, and
 * matches the run page's links at each state.
 */
test('the side panel draws the same run line, small and without faces, at work, stopped, waiting for a yes and done, as an Operator at 1280 px', async ({ browser, backend }, info) => {
  test.slow()
  const name = `Fit line ${randomUUID().slice(0, 6)}`
  const useCaseId = await agentWorkflow(backend, 'alice', name)
  let runId = ''
  try {
    await setMockGithubMode('unavailable')
    runId = await backend.checkNow('alice', useCaseId)
    await backend.waitForState(runId, ['failed'], 150_000)
  } finally {
    await setMockGithubMode('ok')
  }
  const context = await devContext(browser, 'alice', { reducedMotion: true })
  const page = await context.newPage()
  await page.setViewportSize({ width: 1280, height: 1000 })
  const runPage = await context.newPage()
  const panel = page.locator('#side-panel')
  const panelLine = panel.getByRole('list', { name: 'Steps of this run' })
  const found: string[] = []
  const reach = async (state: keyof typeof LINE_STATES) => {
    await expect.poll(async () => (await runLinks(panel)).join(' '), { message: `the panel's run line ${state}`, intervals: [100], timeout: 90_000 }).toMatch(LINE_STATES[state])
    await page.screenshot({ path: path.join(OUT, 'shots', `r11-panel-${state}-alice-1280.png`), caret: 'hide' })
    info.annotations.push({ type: 'shot', description: `r11-panel-${state}-alice-1280` })
    const problems = await fitProblems(page)
    if (problems.length) found.push(`The side panel's run line ${state}:\n${describeProblems(problems).replace(/^/gm, '    ')}`)
  }
  const samePage = async (state: string) => {
    await runPage.goto(`/runs/${runId}`)
    await expect.poll(() => runLinks(runPage), { message: `the run page draws the panel's links ${state}` }).toEqual(await runLinks(panel))
    await expect(runPage.getByRole('list', { name: 'Steps of this run' }).locator('[data-face]').first(), 'the run page has the faces').toBeVisible()
  }
  try {
    await page.goto('/')
    const box = page.getByLabel('Ask the Planner about software versions')
    const newest = page.getByRole('list', { name: 'Conversation with the Planner' }).locator(':scope > li').last()
    await box.fill(`Why did ${name} stop?`)
    await box.press('Enter')
    await expect(newest).toHaveAttribute('data-answer', 'true')
    const opener = newest.locator(`[data-opens="run:${runId}"]`)
    await holdRunAtWork(page, runId)
    await opener.click()
    await reach('at-work')
    await expect(panelLine.locator('[data-face]'), 'the panel draws no faces').toHaveCount(0)
    await panel.getByRole('button', { name: 'Close' }).click()
    await page.unrouteAll({ behavior: 'ignoreErrors' })

    await opener.click()
    await reach('stopped')
    await expect(panelLine, 'the stop is named in words too').toContainText('Stopped here')
    await samePage('stopped')

    await panel.getByRole('button', { name: 'Retry the run' }).click()
    await expect
      .poll(async () => (await runLinks(panel)).join(' '), { message: 'the panel follows the retry: dashes into the step at work, then into the yes', intervals: [100], timeout: 90_000 })
      .toMatch(/^solid( solid)* (flow|wait)( todo)+$/)
    await reach('waiting')
    await samePage('waiting')
    await approve(backend, runId)
    await reach('done')
    await samePage('done')
  } finally {
    await context.close()
  }
  expect(found, found.join('\n')).toEqual([])
})

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

const LONG_CROSS = 'Colour them by team and order them by how long each one has waited, oldest first, with the name of whoever reported it beside each one'
const CARD_SHOTS: ReadonlySet<number> = new Set([1920, 1280, 900, 390])

/** Each state of the Planner's parts list, long crosses included, and the Left out line on a workflow's page (spec 6.5 and 7). */
for (const width of WIDTHS) {
  test(`the parts list fits with ticks, a long cross, a question, a clash and the part I can do, and so does Left out, as an Operator at ${String(width)} px`, async ({ browser, backend }) => {
    test.slow()
    const drafts = async () => (await backend.get<{ drafts: { draft_id: string }[] }>('alice', '/api/v1/drafts')).drafts.map((draft) => draft.draft_id)
    const before = await drafts()
    const context = await devContext(browser, 'alice', { reducedMotion: true })
    const page = await context.newPage()
    await page.setViewportSize({ width, height: width > 900 ? 1000 : 844 })
    const box = page.getByLabel('Ask the Planner about software versions')
    const newest = page.getByRole('list', { name: 'Conversation with the Planner' }).locator(':scope > li').last()
    const found: string[] = []
    const check = async (state: string, name: string, part: Locator) => {
      await page.waitForLoadState('networkidle', { timeout: 5_000 }).catch(() => undefined)
      const problems = await fitProblems(page)
      if (CARD_SHOTS.has(width)) {
        // A tall window, so the whole answer is in the shot rather than cut off by the docked box.
        await page.setViewportSize({ width, height: 2400 })
        await part.screenshot({ path: path.join(OUT, 'shots', `r5-${name}-${String(width)}.png`), caret: 'hide' })
        await page.setViewportSize({ width, height: width > 900 ? 1000 : 844 })
      }
      if (problems.length) found.push(`${state} at ${String(width)} px:\n${describeProblems(problems).replace(/^/gm, '    ')}`)
    }
    const states = [
      ['a set-up card with ticks, a long cross and a question', 'card', `Find bug tickets in MOCK with no update for 10 days and create one ticket that lists them. ${LONG_CROSS}.`, 'How often should it run?'],
      ['the part I can do', 'part', 'Every Friday at 5pm, find tickets in MOCK with no update for 10 days that mention VPN and create one ticket that lists them', 'Ask the team'],
      ['a clash between two days', 'clash', 'Every Monday and Friday at 9am, find bug tickets in MOCK with no update for 10 days and create one ticket that lists them', 'Monday or Friday?'],
    ] as const
    try {
      await page.goto('/')
      for (const [state, name, words, ready] of states) {
        await box.fill(words)
        await box.press('Enter')
        await expect(newest).toHaveAttribute('data-answer', 'true')
        await expect(newest).toContainText(ready, { timeout: 20_000 })
        await check(state, name, newest)
      }
      const before = await page.evaluate(() => [window.scrollX, document.documentElement.scrollLeft])
      await newest.getByRole('button', { name: 'Monday', exact: true }).click()
      await expect(newest).toContainText('Every Monday at 9:00, Singapore time')
      expect(await page.evaluate(() => [window.scrollX, document.documentElement.scrollLeft]), 'answering a question never scrolls the app sideways (ANS-scroll-390)').toEqual(before)
      await check('a clash after the day is chosen', 'clash-chosen', newest)
      const made = await backend.post<{ use_case_id: string }>(
        'alice',
        '/api/v1/agent-use-cases',
        { name: `Left out ${randomUUID().slice(0, 6)}`, instruction: 'Find bug tickets in MOCK with no update for 10 days. Create one ticket that lists them.', agents: AGENTS, left_out: [LONG_CROSS, 'Friday'] },
        undefined,
        [201],
      )
      await page.goto(`/workflows/${made.use_case_id}`)
      await expect(page.getByRole('main')).toContainText('It was set up without those parts.')
      await check('a workflow page with Left out', 'left-out', page.getByRole('main'))
    } finally {
      await context.close()
      // The cards a newer answer replaced were kept as drafts, which alice's draft limit counts.
      await new Promise((resolve) => setTimeout(resolve, 1_500))
      for (const id of await drafts()) if (!before.includes(id)) await backend.send('DELETE', 'alice', `/api/v1/drafts/${id}`)
    }
    expect(found, found.join('\n')).toEqual([])
  })
}
