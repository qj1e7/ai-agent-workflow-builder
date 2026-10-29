/**
 * The checker's checks for P5's live lanes, perf block and review video (docs/design/rebuild-plan.md).
 * Run through scripts/checks/p5.sh, which picks the stack and the lane with --grep @laneN.
 * Evidence goes to $EVID/lane-<n>/ with the file names the plan gives.
 */
import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Browser, type Page } from '@playwright/test'
import { mkdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { Backend, LANGGRAPH, REDIS, setMockGithubMode } from '../live/support/stack'
import { devContext } from '../live/support/ui'
import { assertClean, watchPage } from '../support/test'

const EVID = process.env['EVID'] ?? '/tmp/swarm-p5'
const TARGET = process.env['TARGET'] ?? 'head'
const SAMPLE = Number(process.env['SAMPLE'] ?? '0')
const BASE_URL = process.env['BASE_URL'] ?? 'http://localhost:8080'
const WCAG_22_AA = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']
const STATE_WORDS = /Done: |Now: |Not reached yet: |Waiting for a yes|Stopped here|Not needed|Declined/

interface Approval {
  digest: string
  actions: { fields: { title: string } }[]
  steps: { index: number; status: string }[]
  you_can_decide: boolean
  why_not: string | null
}

interface Step {
  key: string
  state: string
  text: string
}

function laneDir(lane: number | string): string {
  const dir = path.join(EVID, typeof lane === 'number' ? `lane-${lane}` : lane)
  mkdirSync(dir, { recursive: true })
  return dir
}

function save(lane: number | string, name: string, data: unknown): void {
  writeFileSync(path.join(laneDir(lane), name), typeof data === 'string' ? data : JSON.stringify(data, null, 2))
}

async function shotTo(page: Page, lane: number | string, name: string, fullPage = false): Promise<void> {
  await page.waitForFunction(() => document.getAnimations().every((a) => a.playState !== 'running' || a.effect?.getTiming().iterations === Infinity), undefined, { timeout: 3_000 }).catch(() => undefined)
  await page.waitForTimeout(300)
  await page.screenshot({ path: path.join(laneDir(lane), name), caret: 'hide', fullPage })
}

const h1 = (page: Page) => page.getByRole('heading', { level: 1 })

async function stepsOf(page: Page): Promise<Step[]> {
  return page
    .locator('ol[aria-label="Steps of this run"] > li[data-state]')
    .evaluateAll((items) => items.map((li, index) => ({ key: String(index), state: (li as HTMLElement).dataset['state'] ?? '', text: (li as HTMLElement).innerText.replace(/\s+/g, ' ').trim() })))
}

async function stepsSaid(page: Page): Promise<string[]> {
  return page.locator('ol[aria-label="Steps of this run"] > li[data-state]').evaluateAll((items) => items.map((li) => (li.textContent ?? '').replace(/\s+/g, ' ').trim()))
}

async function withBackend<T>(act: (backend: Backend) => Promise<T>): Promise<T> {
  const backend = await Backend.connect(BASE_URL)
  try {
    return await act(backend)
  } finally {
    await backend.dispose()
  }
}

async function ticketsOf(backend: Backend, runId: string) {
  return (await backend.tickets()).filter((ticket) => ticket.run_id === runId)
}

async function eventsOf(backend: Backend, runId: string): Promise<{ seq: number; kind: string; data: Record<string, unknown> }[]> {
  return (await backend.get<{ events: { seq: number; kind: string; data: Record<string, unknown> }[] }>('alice', `/api/v1/runs/${runId}/events?after=0`)).events
}

async function watchLine(page: Page, until: (steps: Step[]) => boolean, limitMs = 60_000): Promise<{ at: number; states: string }[]> {
  const changes: { at: number; states: string }[] = []
  const start = Date.now()
  while (Date.now() - start < limitMs) {
    const steps = await stepsOf(page).catch(() => [])
    const states = steps.map((s) => s.state).join(',')
    if (states && changes.at(-1)?.states !== states) changes.push({ at: Date.now() - start, states })
    if (steps.length > 0 && until(steps)) break
    await page.waitForTimeout(100)
  }
  return changes
}

async function startWhileWatching(page: Page, useCaseId: string, starter = 'alice'): Promise<string> {
  return page.evaluate(
    async ({ useCaseId, starter }) => {
      const started = await fetch(`/api/v1/use-cases/${useCaseId}/runs`, { method: 'POST', headers: { 'X-Dev-User': starter, 'Idempotency-Key': crypto.randomUUID() } })
      const { run_id: runId } = (await started.json()) as { run_id: string }
      history.pushState(null, '', `/runs/${runId}`)
      dispatchEvent(new PopStateEvent('popstate'))
      return runId
    },
    { useCaseId, starter },
  )
}

const atGate = (steps: Step[]) => steps.some((s) => s.state === 'wait')
const finished = (steps: Step[]) => steps.at(-1)?.state === 'done'

function reached(changes: { states: string }[]): number[] {
  return changes.map((c) => c.states.split(',').reduce((far, state, index) => (state === 'todo' ? far : index), 0))
}

test('@lane1-trunk trunk has no run page', async ({ browser }) => {
  const context = await devContext(browser, 'alice')
  const page = await context.newPage()
  await page.goto('/runs/run_from_head')
  await expect(h1(page)).toBeVisible()
  const heading = (await h1(page).innerText()).trim()
  await shotTo(page, 1, 'p5-live-run-trunk.png')
  save(1, 'p5-trunk.json', { target: 'trunk', url: page.url(), heading })
  expect(heading).toBe('Page not found')
  await context.close()
})

test('@lane1 alice watches a new check move along the line and stop at the gate', async ({ browser }) => {
  await withBackend(async (backend) => {
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    const watch = watchPage(page)
    const attempts: { runId: string; changes: { at: number; states: string }[] }[] = []
    for (let attempt = 0; attempt < 3 && new Set(reached(attempts.at(-1)?.changes ?? [])).size < 2; attempt += 1) {
      const useCaseId = await backend.freshWatchlist('alice')
      await page.goto('/runs/none')
      await expect(h1(page)).toHaveText('Run not found')
      const started = await startWhileWatching(page, useCaseId)
      attempts.push({ runId: started, changes: await watchLine(page, atGate) })
    }
    const { runId, changes } = attempts.at(-1) ?? { runId: '', changes: [] }
    const far = reached(changes)
    await expect(h1(page)).toHaveText(/waiting for a yes$/)
    await page.evaluate(() => window.scrollTo(0, 0))
    await shotTo(page, 1, 'p5-live-run.png')
    const fills = await page.locator('ol[aria-label="Steps of this run"] > li[aria-hidden="true"]').evaluateAll((items) => items.map((li) => getComputedStyle(li).transform))
    const steps = await stepsOf(page)
    save(1, 'p5-live-run.json', { runId, changes, reached: far, steps, fills, attempts })
    expect(new Set(far).size, 'the line was seen at several steps, not only at the end').toBeGreaterThanOrEqual(2)
    expect(far.every((value, index) => index === 0 || value >= (far[index - 1] ?? 0)), 'the line only moves forward').toBe(true)
    expect(steps.map((s) => s.state).slice(0, -2), 'it stops at the gate with every step before it done').toEqual([...steps.slice(0, -3).map(() => 'done'), 'wait'])
    expect(steps.slice(-2).map((s) => s.state)).toEqual(['todo', 'todo'])
    assertClean(watch)
    await context.close()
  })
})

test('@lane2 bob approves a waiting run and the page shows the ticket created and the run Done', async ({ browser }) => {
  await withBackend(async (backend) => {
    const { runId, approvalId } = await backend.waitingRun('alice')
    const context = await devContext(browser, 'bob')
    const page = await context.newPage()
    const watch = watchPage(page)
    await page.goto(`/runs/${runId}`)
    await expect(page.getByRole('button', { name: 'Approve 1 ticket' })).toBeVisible()
    await page.getByRole('button', { name: 'Approve 1 ticket' }).click()
    await expect(h1(page)).toHaveText('1 ticket created in Jira', { timeout: 60_000 })
    const tickets = await ticketsOf(backend, runId)
    await expect(page.getByRole('main')).toContainText(`Created ${tickets[0]?.key ?? 'nothing'} in Jira.`)
    await expect(page.getByRole('main')).toContainText('Bob approved, and the platform created the ticket.')
    const steps = await stepsOf(page)
    await page.evaluate(() => window.scrollTo(0, 0))
    await shotTo(page, 2, 'p5-approved.png', true)
    save(2, 'p5-approved.json', { runId, approvalId, run: await backend.run(runId), tickets, steps })
    expect(tickets).toHaveLength(1)
    expect(steps.every((s) => s.state === 'done')).toBe(true)
    expect((await backend.run(runId)).state).toBe('succeeded')
    assertClean(watch)
    await context.close()
  })
})

test('@lane3 bob declines a waiting run and nothing is written', async ({ browser }) => {
  await withBackend(async (backend) => {
    const { runId } = await backend.waitingRun('alice')
    const before = await backend.tickets()
    const context = await devContext(browser, 'bob')
    const page = await context.newPage()
    const watch = watchPage(page)
    await page.goto(`/runs/${runId}`)
    await page.getByRole('button', { name: 'Decline' }).click()
    await expect(h1(page)).toHaveText('Declined, nothing was written', { timeout: 60_000 })
    await expect(page.getByRole('main')).toContainText('Bob declined, so nothing was written.')
    const steps = await stepsOf(page)
    await page.evaluate(() => window.scrollTo(0, 0))
    await shotTo(page, 3, 'p5-declined.png', true)
    const after = await backend.tickets()
    save(3, 'p5-declined.json', { runId, run: await backend.run(runId), ticketsBefore: before.length, ticketsAfter: after.length, forThisRun: await ticketsOf(backend, runId), steps })
    expect(after.length).toBe(before.length)
    expect(await ticketsOf(backend, runId)).toEqual([])
    expect(steps.map((s) => s.state).slice(-3)).toEqual(['declined', 'skip', 'done'])
    expect((await backend.run(runId)).state).toBe('rejected')
    assertClean(watch)
    await context.close()
  })
})

async function viewWaiting(browser: Browser, user: string, lane: number, file: string): Promise<{ text: string; approve: number; approval: Approval; runId: string }> {
  return withBackend(async (backend) => {
    const { runId, approvalId } = await backend.waitingRun('alice')
    const approval = await backend.get<Approval>(user, `/api/v1/approvals/${approvalId}`)
    const context = await devContext(browser, user)
    const page = await context.newPage()
    const watch = watchPage(page)
    await page.goto(`/runs/${runId}`)
    await expect(h1(page)).toHaveText('1 ticket is waiting for a yes')
    await expect(page.locator('#decision')).toBeFocused()
    await shotTo(page, lane, file)
    const text = await page.getByRole('main').innerText()
    const approve = await page.getByRole('button', { name: /^Approve/ }).count()
    save(lane, file.replace('.png', '.json'), { user, runId, approval, approveButtons: approve, decision: await page.locator('#decision').innerText() })
    assertClean(watch)
    await context.close()
    return { text, approve, approval, runId }
  })
}

test('@lane4 alice sees that someone else must say yes, and no Approve button', async ({ browser }) => {
  const seen = await viewWaiting(browser, 'alice', 4, 'p5-own-run.png')
  expect(seen.approval).toMatchObject({ you_can_decide: false, why_not: 'own_work' })
  expect(seen.approve).toBe(0)
  expect(seen.text).toContain('You started this run, so you can’t approve it. Nobody approves their own work.')
  expect(seen.text).toContain(seen.approval.actions[0]?.fields.title ?? '')
})

test('@lane5 carol sees the proposal and no Approve button', async ({ browser }) => {
  const seen = await viewWaiting(browser, 'carol', 5, 'p5-not-approver.png')
  expect(seen.approval).toMatchObject({ you_can_decide: false, why_not: 'not_an_approver' })
  expect(seen.approve).toBe(0)
  expect(seen.text).toContain('Only an Approver can decide.')
  expect(seen.text).toContain('This is exactly what will be written, and nothing else.')
  expect(seen.text).toContain(seen.approval.actions[0]?.fields.title ?? '')
})

test('@lane6 a failed run marks the step that stopped and shows the troubleshooter’s reason below it', async ({ browser }) => {
  await withBackend(async (backend) => {
    await setMockGithubMode('unavailable')
    let runId = ''
    try {
      runId = await backend.startCheck('alice')
      await backend.waitForState(runId, ['failed'], 90_000).catch(async (error: unknown) => {
        if ((await backend.run(runId)).state !== 'failed') throw error
      })
    } finally {
      await setMockGithubMode('ok')
    }
    const advice = await backend.get('alice', `/api/v1/runs/${runId}/troubleshoot`)
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    const watch = watchPage(page)
    await page.goto(`/runs/${runId}`)
    await expect(h1(page)).toHaveText(/^Stopped at /)
    await expect(page.locator('#decision')).toBeFocused()
    const failed = page.locator('ol[aria-label="Steps of this run"] > li[data-state="fail"]')
    await expect(failed).toHaveCount(1)
    await expect(failed).toContainText('Stopped here')
    const reason = page.locator('#decision')
    await expect(reason).toContainText('AI troubleshooter')
    await expect(reason).toContainText('What happened')
    await expect(reason).toContainText('What to do')
    const lineBox = await page.locator('ol[aria-label="Steps of this run"]').boundingBox()
    const reasonBox = await reason.boundingBox()
    await page.evaluate(() => window.scrollTo(0, 0))
    await shotTo(page, 6, 'p5-failed.png', true)
    const words = await reason.innerText()
    save(6, 'p5-failed.json', { runId, run: await backend.run(runId), troubleshoot: advice, steps: await stepsOf(page), reasonOnPage: words, lineBox, reasonBox })
    expect((reasonBox?.y ?? 0) > (lineBox?.y ?? 0) + (lineBox?.height ?? 0), 'the reason is below the line').toBe(true)
    expect(words).not.toMatch(/use case|template|room lead|release checker/i)
    assertClean(watch)
    await context.close()
  })
})

test('@lane7 a reload mid-run redraws the steps so far and keeps following new events', async ({ browser }) => {
  await withBackend(async (backend) => {
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    const watch = watchPage(page)
    const useCaseId = await backend.freshWatchlist('alice')
    await page.goto('/runs/none')
    await expect(h1(page)).toHaveText('Run not found')
    const runId = await startWhileWatching(page, useCaseId)
    const beforeReload = await watchLine(page, (steps) => steps.slice(1).some((s) => s.state === 'done' || s.state === 'now' || s.state === 'wait'))
    const doneBefore = (await stepsOf(page)).filter((s) => s.state === 'done').length
    await page.reload()
    await expect(h1(page)).toBeVisible()
    const firstDrawn = await stepsOf(page)
    const toGate = await watchLine(page, atGate)
    const approvalId = await backend.approvalIdOf(runId)
    const forBob = await backend.get<Approval>('bob', `/api/v1/approvals/${approvalId}`)
    const open = forBob.steps.find((s) => s.status === 'open')
    await backend.post('bob', `/api/v1/approvals/${approvalId}/decisions`, { step: open?.index ?? 0, verdict: 'approve', digest: forBob.digest }, {}, [201])
    const toDone = await watchLine(page, finished)
    await expect(h1(page)).toHaveText('1 ticket created in Jira')
    const navigations = await page.evaluate(() => performance.getEntriesByType('navigation').length)
    await page.evaluate(() => window.scrollTo(0, 0))
    await shotTo(page, 7, 'p5-reload.png', true)
    save(7, 'p5-reload.json', { runId, beforeReload, doneBefore, firstDrawnAfterReload: firstDrawn, toGate, toDone, navigationsAfterReload: navigations })
    expect(firstDrawn.filter((s) => s.state !== 'todo').length, 'the reload draws the steps reached so far at once').toBeGreaterThanOrEqual(doneBefore)
    expect(toDone.at(-1)?.states.split(',').every((s) => s === 'done'), 'the page followed the run to Done without another reload').toBe(true)
    assertClean(watch)
    await context.close()
  })
})

test('@lane8 the Teams link opens a run at the decision, and approving in the panel updates the run page', async ({ browser }) => {
  await withBackend(async (backend) => {
    const first = await backend.waitingRun('alice')
    const secondRun = await backend.addAndCheck('alice', REDIS)
    await backend.waitForState(secondRun, ['awaiting_approval'])
    const second = { runId: secondRun, approvalId: await backend.approvalIdOf(secondRun) }
    const context = await devContext(browser, 'bob')
    const page = await context.newPage()
    const watch = watchPage(page)
    await page.goto('/')
    const teams = page.getByRole('button', { name: /^Teams, practice copy/ })
    await teams.click()
    const drawer = page.getByRole('dialog', { name: 'Teams, practice copy' })
    const firstCard = drawer.locator(`li[data-approval-id="${first.approvalId}"]`)
    await expect(firstCard).toBeVisible()
    await firstCard.getByRole('link', { name: 'Open in Workflow Builder' }).click()
    await expect(page).toHaveURL(new RegExp(`/approvals/${first.approvalId}$`))
    await expect(page.locator('#decision')).toBeFocused()
    await expect(page.getByRole('button', { name: 'Approve 1 ticket' })).toBeVisible()
    const linkLanding = { url: page.url(), heading: await h1(page).innerText(), focused: await page.evaluate(() => document.activeElement?.id ?? '') }

    await page.goto(`/runs/${second.runId}`)
    await expect(h1(page)).toHaveText('1 ticket is waiting for a yes')
    await page.evaluate(() => {
      ;(window as unknown as { kept: boolean }).kept = true
    })
    await teams.click()
    const secondCard = drawer.locator(`li[data-approval-id="${second.approvalId}"]`)
    await secondCard.getByRole('button', { name: 'Approve' }).click()
    await expect(secondCard.getByText('Approved by Bob')).toBeVisible({ timeout: 30_000 })
    await expect(h1(page)).toHaveText('1 ticket created in Jira', { timeout: 60_000 })
    await shotTo(page, 8, 'p5-teams-approve.png')
    const kept = await page.evaluate(() => (window as unknown as { kept?: boolean }).kept === true)
    await page.keyboard.press('Escape')
    await expect(drawer).toBeHidden()
    save(8, 'p5-teams-approve.json', {
      first,
      second,
      linkLanding,
      secondRun: await backend.run(second.runId),
      firstRun: await backend.run(first.runId),
      ticketsForSecond: await ticketsOf(backend, second.runId),
      pageNotReloaded: kept,
    })
    expect(linkLanding.focused).toBe('decision')
    expect(kept, 'the run page updated without a reload').toBe(true)
    expect((await backend.run(first.runId)).state, 'opening the link decides nothing').toBe('awaiting_approval')
    assertClean(watch)
    await context.close()
  })
})

test('@lane9 reduced motion, words for every step, and axe on the run page and the Teams panel', async ({ browser }) => {
  await withBackend(async (backend) => {
    const playRun = async (reducedMotion: boolean) => {
      const context = await devContext(browser, 'alice', { reducedMotion })
      const page = await context.newPage()
      const useCaseId = await backend.freshWatchlist('alice')
      await page.goto('/runs/none')
      await expect(h1(page)).toHaveText('Run not found')
      await page.evaluate(() => {
        const seen = { frames: 0, maxRunning: 0, names: [] as string[] }
        ;(window as unknown as { motionSeen: typeof seen }).motionSeen = seen
        const sample = () => {
          const running = document.getAnimations().filter((a) => a.playState === 'running')
          seen.frames += 1
          seen.maxRunning = Math.max(seen.maxRunning, running.length)
          for (const a of running) {
            const name = 'animationName' in a ? String((a as CSSAnimation).animationName) : 'transition'
            if (!seen.names.includes(name)) seen.names.push(name)
          }
        }
        setInterval(sample, 5)
      })
      const runId = await startWhileWatching(page, useCaseId)
      const toGate = await watchLine(page, atGate)
      const said = await stepsSaid(page)
      const approvalId = await backend.approvalIdOf(runId)
      const forBob = await backend.get<Approval>('bob', `/api/v1/approvals/${approvalId}`)
      await backend.post('bob', `/api/v1/approvals/${approvalId}/decisions`, { step: 0, verdict: 'approve', digest: forBob.digest }, {}, [201])
      const toDone = await watchLine(page, finished)
      await page.waitForTimeout(1_000)
      const seen = await page.evaluate(() => (window as unknown as { motionSeen: { frames: number; maxRunning: number; names: string[] } }).motionSeen)
      const saidDone = await stepsSaid(page)
      await context.close()
      return { runId, toGate, toDone, framesSampled: seen.frames, maxRunning: seen.maxRunning, animating: seen.names, said, saidDone }
    }
    const control = await playRun(false)
    const motion = await playRun(true)

    const { runId } = await backend.waitingRun('alice')
    const runs: Record<string, unknown>[] = []
    for (const [width, phone] of [
      ['1440', false],
      ['390', true],
    ] as const) {
      const context = await devContext(browser, 'bob', { phone, reducedMotion: true })
      const page = await context.newPage()
      await page.goto(`/runs/${runId}`)
      await expect(page.getByRole('button', { name: 'Approve 1 ticket' })).toBeVisible()
      for (const [where, open] of [
        ['run page', false],
        ['Teams panel', true],
      ] as const) {
        if (open) {
          await page.getByRole('button', { name: /^Teams, practice copy/ }).click()
          await expect(page.getByRole('dialog', { name: 'Teams, practice copy' })).toBeVisible()
          await expect(page.getByRole('dialog').getByRole('listitem').first()).toBeVisible()
        }
        const result = await new AxeBuilder({ page }).withTags(WCAG_22_AA).analyze()
        runs.push({
          where,
          width,
          axe: result.testEngine.version,
          violations: result.violations.map((v) => ({ id: v.id, impact: v.impact, help: v.help, nodes: v.nodes.map((n) => ({ target: n.target, summary: n.failureSummary })) })),
          passes: result.passes.length,
        })
        await page.screenshot({ path: path.join(laneDir(9), `p5-axe-${where.replace(' ', '-')}-${width}.png`) })
      }
      await context.close()
    }
    const violations = runs.flatMap((r) => (r['violations'] as { id: string }[]).map((v) => `${String(r['where'])} @${String(r['width'])}: ${v.id}`))
    save(9, 'p5-reduced-motion-axe.json', { tags: WCAG_22_AA, motion, controlWithMotionOn: control, axe: runs, totalViolations: violations.length })
    expect(control.maxRunning, 'with motion on, the sampler sees animations').toBeGreaterThan(0)
    expect(motion.maxRunning, `animations running under reduced motion: ${motion.animating.join(', ')}`).toBe(0)
    expect([...motion.said, ...motion.saidDone].filter((said) => !STATE_WORDS.test(said)), 'steps that do not say their state in words').toEqual([])
    expect(motion.framesSampled, 'samples taken while the run played').toBeGreaterThan(100)
    expect(violations, 'axe violations').toEqual([])
  })
})

test('@lane10 pressing Approve twice records one decision and one set of tickets', async ({ browser }) => {
  await withBackend(async (backend) => {
    const { runId, approvalId } = await backend.waitingRun('alice')
    const context = await devContext(browser, 'bob')
    const page = await context.newPage()
    const watch = watchPage(page)
    const posts: { url: string; status: number }[] = []
    page.on('response', (response) => {
      if (response.request().method() === 'POST' && response.url().includes(`/approvals/${approvalId}/decisions`)) posts.push({ url: response.url(), status: response.status() })
    })
    await page.goto(`/runs/${runId}`)
    const approve = page.getByRole('button', { name: 'Approve 1 ticket' })
    await expect(approve).toBeVisible()
    await approve.evaluate((button: HTMLButtonElement) => {
      button.click()
      button.click()
    })
    await expect(h1(page)).toHaveText('1 ticket created in Jira', { timeout: 60_000 })
    await page.waitForTimeout(1_000)
    const decided = (await eventsOf(backend, runId)).filter((event) => event.kind === 'approval_decided')
    const tickets = await ticketsOf(backend, runId)
    save(10, 'p5-double-click.json', { runId, approvalId, decisionPosts: posts, approvalDecidedEvents: decided, tickets })
    expect(posts, 'the page sent one decision').toHaveLength(1)
    expect(decided).toHaveLength(1)
    expect(tickets).toHaveLength(1)
    assertClean(watch)
    await context.close()
  })
})

async function doneRun(backend: Backend): Promise<string> {
  const done = (await backend.runs('alice')).find((run) => run.state === 'succeeded' && run.outcome === 'written')
  if (done) return done.run_id
  const { runId, approvalId } = await backend.waitingRun('alice', [LANGGRAPH])
  const approval = await backend.get<Approval>('bob', `/api/v1/approvals/${approvalId}`)
  await backend.post('bob', `/api/v1/approvals/${approvalId}/decisions`, { step: 0, verdict: 'approve', digest: approval.digest }, {}, [201])
  await backend.waitForState(runId, ['succeeded'])
  return runId
}

test('@perf largest contentful paint of a done run', async ({ browser }) => {
  const runId = await withBackend(doneRun)
  const context = await devContext(browser, 'alice')
  const page = await context.newPage()
  await page.goto(`/runs/${runId}`, { waitUntil: 'load' })
  await expect(h1(page)).toHaveText('1 ticket created in Jira', { timeout: 30_000 })
  await page.waitForTimeout(1_500)
  const measured = await page.evaluate(
    () =>
      new Promise<{ entries: { startTime: number; element: string }[] }>((resolve) => {
        const entries: { startTime: number; element: string }[] = []
        const observer = new PerformanceObserver((list) => {
          for (const e of list.getEntries() as (PerformanceEntry & { element: Element | null })[]) {
            entries.push({ startTime: e.startTime, element: e.element ? `${e.element.tagName.toLowerCase()} "${(e.element.textContent ?? '').trim().slice(0, 40)}"` : 'gone' })
          }
        })
        observer.observe({ type: 'largest-contentful-paint', buffered: true })
        setTimeout(() => {
          observer.disconnect()
          resolve({ entries })
        }, 500)
      }),
  )
  const last = measured.entries.at(-1)
  expect(last, 'the browser reported a largest contentful paint').toBeDefined()
  save('perf', `lcp-${TARGET}-${SAMPLE}.json`, { target: TARGET, sample: SAMPLE, runId, lcp: last?.startTime ?? -1, element: last?.element ?? '', entries: measured.entries })
  await context.close()
})

test('@review-video a run that waits, is approved on its page, and finishes', async ({ browser }) => {
  test.setTimeout(180_000)
  await withBackend(async (backend) => {
    const context = await browser.newContext({
      viewport: { width: 1440, height: 900 },
      recordVideo: { dir: path.join(EVID, '.review-video'), size: { width: 1440, height: 900 } },
      locale: 'en-SG',
      timezoneId: 'Asia/Singapore',
    })
    await context.addInitScript(() => window.localStorage.setItem('portal.dev-user', 'bob'))
    const page = await context.newPage()
    const video = page.video()
    const useCaseId = await backend.freshWatchlist('alice')
    await page.goto('/')
    await expect(h1(page)).toBeVisible()
    await page.waitForTimeout(2_500)
    await page.goto('/runs/none')
    await expect(h1(page)).toBeVisible()
    await startWhileWatching(page, useCaseId)
    await watchLine(page, atGate)
    await page.waitForTimeout(4_000)
    await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'smooth' }))
    await page.waitForTimeout(4_500)
    await page.locator('#decision').scrollIntoViewIfNeeded()
    await page.waitForTimeout(4_000)
    await page.getByRole('button', { name: 'Approve 1 ticket' }).hover()
    await page.waitForTimeout(1_000)
    await page.getByRole('button', { name: 'Approve 1 ticket' }).click()
    await watchLine(page, finished)
    await page.waitForTimeout(4_000)
    await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'smooth' }))
    await page.waitForTimeout(4_500)
    await page.getByRole('button', { name: /^Teams, practice copy/ }).click()
    await page.waitForTimeout(5_000)
    await page.keyboard.press('Escape')
    await page.waitForTimeout(2_000)
    await context.close()
    await video?.saveAs(path.join(EVID, 'p5-review.webm'))
  })
})
