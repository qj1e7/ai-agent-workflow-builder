import { randomUUID } from 'node:crypto'
import path from 'node:path'
import type { Locator, Page } from '@playwright/test'
import { expectAccessible } from '../support/axe'
import { assertClean, watchPage } from '../support/test'
import type { Backend } from './support/stack'
import { expect, test } from './support/test'
import { devContext, OUT, shot } from './support/ui'

const replyItem = (page: Page, requestId: string) => page.locator(`li[data-home-item="reply:${requestId}"]`)
const followingRow = (page: Page, requestId: string) => page.locator(`li[data-request="${requestId}"]`)
const draftRow = (page: Page, draftId: string) => page.locator(`li[data-draft="${draftId}"]`)
/** The rows in Needs you. The page shows every one of them, so this is the number the tab counts. */
const countInHeading = (page: Page): Promise<number> => page.getByRole('main').locator('li[data-home-item]').count()

interface Made {
  readonly requestId: string
  readonly note: string
}

const LONG_LINK = `https://example.com/${'a'.repeat(190)}`

async function askAndAnswer(backend: Backend, word: string, long = false): Promise<Made> {
  const note = `Please add ${word} ${randomUUID().slice(0, 6)}${long ? ` ${LONG_LINK}` : ''}`
  const made = await backend.post<{ request_id: string }>('alice', '/api/v1/team-requests', { kind: 'ask_the_team', about: { capability: 'email.send' }, note }, { 'Idempotency-Key': randomUUID() }, [201])
  await backend.post('bob', `/api/v1/team-requests/${made.request_id}/replies`, { text: `Not on the plan yet, we will tell you.${long ? ` ${LONG_LINK}` : ''}` }, undefined, [201])
  return { requestId: made.request_id, note }
}

async function draftFor(backend: Backend, label: string): Promise<{ id: string; name: string }> {
  const id = randomUUID()
  const name = `Lane draft ${label} ${id.slice(0, 6)}`
  const saved = await backend.send('PUT', 'alice', `/api/v1/drafts/${id}`, { step: null, content: { name, intent: 'Every Monday, list the tickets closed last week.' } })
  expect(saved.status, `alice saves a draft: ${JSON.stringify(saved.body)}`).toBe(200)
  return { id, name }
}

async function homeOf(backend: Backend, user: string) {
  return backend.get<{ replied: { request_id: string }[]; following_up: { request_id: string }[]; waiting_on_others: { run_id: string }[] }>(user, '/api/v1/home')
}

test('a reply is in the asker’s Needs you until they open it, then it stays under Following up', async ({ browser, backend }, info) => {
  const { requestId, note } = await askAndAnswer(backend, 'email')
  const context = await devContext(browser, 'alice')
  const page = await context.newPage()
  const watch = watchPage(page)
  await page.goto('/workflows')
  await expect(replyItem(page, requestId)).toBeVisible()
  await expect(replyItem(page, requestId)).toContainText('Bob replied to your request')
  await expect(followingRow(page, requestId)).toContainText('Not on the plan yet')
  const before = await countInHeading(page)
  await expect(followingRow(page, requestId)).toContainText(note)
  await shot(page, info, 'n9b-asker-needs-you')

  await replyItem(page, requestId).getByRole('link').click()
  await expect(page).toHaveURL(new RegExp(`/workflows\\?request=${requestId}$`))
  await expect(page.getByRole('article')).toContainText(note)
  await expect(page.getByRole('article')).toContainText('You asked the team')
  await expect(page.getByRole('list', { name: 'Replies' })).toContainText('Not on the plan yet')
  await expect.poll(async () => (await homeOf(backend, 'alice')).replied.map((item) => item.request_id), { message: 'opening it marks the reply as read' }).not.toContain(requestId)
  await shot(page, info, 'n9b-asker-request')

  await page.getByRole('link', { name: 'Workflows', exact: true }).first().click()
  await expect(page).toHaveURL(/\/workflows$/)
  await expect(followingRow(page, requestId)).toBeVisible()
  await expect(replyItem(page, requestId)).toHaveCount(0)
  await expect.poll(() => countInHeading(page), { message: 'Needs you went down by one' }).toBeLessThanOrEqual(before - 1)
  await page.goto('/')
  await expect(replyItem(page, requestId), 'Home agrees').toHaveCount(0)
  assertClean(watch)
  await context.close()
})

test('a teammate opens the card’s link, reads who asked, and replies; the asker sees the reply', async ({ browser, backend }, info) => {
  const asked = await backend.post<{ request_id: string }>('alice', '/api/v1/team-requests', { kind: 'ask_the_team', about: { capability: 'chat.post' }, note: `Post to our chat ${randomUUID().slice(0, 6)}` }, { 'Idempotency-Key': randomUUID() }, [201])
  const link = `/workflows?request=${asked.request_id}`
  const context = await devContext(browser, 'carol')
  const page = await context.newPage()
  await page.goto(link)
  await expect(page.getByRole('article')).toContainText('Alice asked the team')
  await expect(page.getByRole('article')).toContainText('Post to our chat')
  await expect(page.getByText('Nobody has replied yet.')).toBeVisible()
  await expect(page.getByRole('button', { name: /^Approve|^Decline/ })).toHaveCount(0)
  await page.getByLabel('Your reply').fill('We will look at it next sprint.')
  await page.getByLabel('Done, nothing more will happen').check()
  await page.getByRole('button', { name: 'Send reply' }).click()
  await expect(page.getByText('Reply sent.')).toBeVisible()
  await expect(page.getByRole('list', { name: 'Replies' })).toContainText('We will look at it next sprint.')
  await expect(page.getByRole('article')).toContainText('Done')
  await shot(page, info, 'n9b-teammate-replied')
  await context.close()

  const seen = await homeOf(backend, 'alice')
  expect(seen.replied.map((item) => item.request_id), 'the asker has a reply to read').toContain(asked.request_id)
  expect(seen.following_up.map((item) => item.request_id)).toContain(asked.request_id)
  const refused = await backend.send('POST', 'carol', `/api/v1/team-requests/${asked.request_id}/seen`, { through: new Date().toISOString() })
  expect(refused.status, 'only the asker can mark it read').toBe(403)
})

test('the asker adds a note to her own request and it stays Open, then she marks it done', async ({ browser, backend }, info) => {
  const asked = await backend.post<{ request_id: string }>('alice', '/api/v1/team-requests', { kind: 'ask_the_team', about: { capability: 'chat.post' }, note: `Post to our chat ${randomUUID().slice(0, 6)}` }, { 'Idempotency-Key': randomUUID() }, [201])
  const context = await devContext(browser, 'alice')
  const page = await context.newPage()
  await page.goto(`/workflows?request=${asked.request_id}`)
  const article = page.getByRole('article')
  await expect(article).toContainText('You asked the team')
  await expect(page.getByRole('radio')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Add', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Mark done' })).toBeVisible()
  await page.getByLabel('Your note').fill('It is for the Friday report.')
  await page.getByRole('button', { name: 'Add', exact: true }).click()
  await expect(page.getByText('Added.')).toBeVisible()
  const replies = page.getByRole('list', { name: 'Replies' })
  await expect(replies).toContainText('It is for the Friday report.')
  await expect(replies).toContainText('Added to the request')
  await expect(replies).not.toContainText('Answered')
  await expect(article.locator('[data-status]').first()).toHaveAttribute('data-status', 'open')
  expect((await backend.get<{ status: string }>('alice', `/api/v1/team-requests/${asked.request_id}`)).status).toBe('open')
  await shot(page, info, 'n9b-asker-adds-a-note')

  await page.getByLabel('Your note').fill('Not needed any more.')
  await page.getByRole('button', { name: 'Mark done' }).click()
  await expect(replies).toContainText('Marked Done')
  expect((await backend.get<{ status: string }>('alice', `/api/v1/team-requests/${asked.request_id}`)).status).toBe('done')
  await context.close()
})

test('a link to a request that does not exist says so plainly', async ({ browser }) => {
  const context = await devContext(browser, 'bob')
  const page = await context.newPage()
  await page.goto('/workflows?request=trq_nothing_here')
  await expect(page.getByRole('heading', { level: 2, name: 'There is no request with that link' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Workflows', exact: true }).first()).toBeVisible()
  await context.close()
})

test('alice sees the run she started as Waiting for a yes on its workflow’s row, whose banner opens the run, and Workflows has no Waiting on others', async ({ browser, backend }) => {
  const { runId } = await backend.waitingRun('alice')
  const context = await devContext(browser, 'alice')
  const page = await context.newPage()
  await page.goto('/workflows')
  const row = page.locator('li[data-workflow-id]').filter({ hasText: 'Software watchlist' })
  await expect(row).toContainText('Waiting for a yes')
  await expect(page.getByRole('region', { name: 'Waiting on others' })).toHaveCount(0)
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  await expect(page.locator(`[data-waiting="${runId}"]`)).toHaveCount(0)
  await context.close()
})

test('a connection that does not answer sends Alice to the Connections tab, where Check now clears it everywhere once it works', async ({ browser, backend }) => {
  const answering = (on: boolean) => backend.post('alice', '/api/v1/dev/practice-jira/answering', { answering: on })
  await answering(false)
  await backend.post('alice', '/api/v1/settings/connections/jira/check')
  const context = await devContext(browser, 'alice')
  const page = await context.newPage()
  try {
    await page.goto('/workflows')
    const item = page.locator('li[data-home-item="connection:jira"]')
    await expect(item).toBeVisible()
    await expect(item.getByRole('button')).toHaveCount(0)
    const before = await countInHeading(page)
    await item.getByRole('link').click()
    await expect(page).toHaveURL(/\/settings$|\/settings\?tab=connections$/)
    const card = page.locator('[data-connection="jira"]')
    await card.getByRole('button', { name: 'Check now for Jira' }).click()
    await expect(card.getByRole('status')).toContainText('Checked just now.')
    await expect(card.getByRole('status')).not.toContainText('answered')

    await answering(true)
    await card.getByRole('button', { name: 'Check now for Jira' }).click()
    await expect(card.getByRole('status')).toHaveText('Checked just now. Jira answered.')
    await page.goto('/workflows')
    await expect(page.locator('li[data-home-item="connection:jira"]')).toHaveCount(0)
    await expect.poll(() => countInHeading(page)).toBe(before - 1)
  } finally {
    await answering(true)
    await backend.post('alice', '/api/v1/settings/connections/jira/check')
    await context.close()
  }
})

test('a draft is a row under All workflows with the pill Draft, never in Needs you, and its one link opens it in the chat', async ({ browser, backend }, info) => {
  const draft = await draftFor(backend, 'row')
  const context = await devContext(browser, 'alice')
  const page = await context.newPage()
  try {
    await page.goto('/workflows')
    const row = draftRow(page, draft.id)
    await expect(row).toContainText(draft.name)
    await expect(row).toContainText('Only your words are saved.')
    await expect(row.getByText('Draft', { exact: true }), 'the row has one pill, Draft').toHaveCount(1)
    await expect(row.getByRole('button'), 'the row is one link, and Discard is on the draft’s card in the chat').toHaveCount(0)
    await expect(page.getByRole('region', { name: 'Needs you' }).locator('li[data-draft]'), 'the strip does not count a draft, so Needs you does not list one').toHaveCount(0)
    await expect(row.getByRole('link')).toHaveAttribute('href', `/?draft=${draft.id}`)
    await shot(page, info, 'n9b-draft-row')
  } finally {
    await backend.delete('alice', `/api/v1/drafts/${draft.id}`)
    await context.close()
  }
})

test('the search and the filters show once there are more than ten workflows, and narrow the list', async ({ browser, backend, request }, info) => {
  await backend.waitingRun('alice')
  const listed = async () => ((await (await request.get('/api/v1/use-cases', { headers: { 'X-Dev-User': 'alice' } })).json()) as { use_cases: unknown[] }).use_cases.length
  for (let have = await listed(); have <= 10; have += 1) {
    await backend.post('alice', '/api/v1/agent-use-cases', { name: `Search lane ${randomUUID().slice(0, 6)}`, instruction: 'Check LangGraph for a new release and raise a ticket in MOCK.', agents: [{ card_id: 'crd_version_checker', values: { 'GitHub repository': 'langchain-ai/langgraph', 'Jira project': 'MOCK' } }] }, undefined, [201])
  }
  const context = await devContext(browser, 'alice')
  const page = await context.newPage()
  await page.goto('/workflows')
  const search = page.getByRole('searchbox', { name: 'Find a workflow' })
  await expect(search).toBeVisible()
  await expect(page.getByRole('group', { name: 'Show' }).getByRole('button', { name: 'Stopped', exact: true })).toBeVisible()
  await expect(page.getByRole('main').locator('li[data-workflow-id] [data-state]')).toHaveCount(0)
  await shot(page, info, 'n9b-search-open')
  await search.fill('Software watchlist')
  await expect(page.getByRole('main').locator('li[data-workflow-id]')).toHaveCount(1)
  await page.getByRole('button', { name: 'Paused', exact: true }).click()
  await expect(page.getByText('No workflows match')).toBeVisible()
  await context.close()
})

for (const phone of [false, true]) {
  test(`Workflows with every section, and a request, pass WCAG 2.2 AA and do not scroll sideways at ${phone ? '390' : '1440'} px, even with a long link in a request and in a reply`, async ({ browser, backend }, info) => {
    const { requestId } = await askAndAnswer(backend, phone ? 'phone' : 'desktop', true)
    const draft = await draftFor(backend, phone ? 'phone' : 'desktop')
    await backend.waitingRun('alice')
    const context = await devContext(browser, 'alice', { phone })
    const page = await context.newPage()
    const sideways = async () => {
      const widths = await page.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth])
      expect(widths[0], 'no sideways scroll').toBeLessThanOrEqual(widths[1] ?? 0)
    }
    const name = phone ? 'phone' : 'desktop'
    await page.goto('/workflows')
    await expect(replyItem(page, requestId)).toBeVisible()
    await expect(draftRow(page, draft.id)).toBeVisible()
    await expect(followingRow(page, requestId)).toBeVisible()
    await page.waitForFunction(() => document.getAnimations().length === 0)
    await expectAccessible(page, path.join(OUT, 'axe'), `workflows-sections-${name}`)
    await sideways()
    await shot(page, info, `n9b-workflows-${name}`)
    const row = await followingRow(page, requestId).evaluate((li) => {
      const box = li.getBoundingClientRect()
      return Math.max(0, ...[...li.querySelectorAll('span')].map((span) => span.getBoundingClientRect().right - box.right))
    })
    expect(row, 'the words of a Following up row stay inside it').toBeLessThanOrEqual(0)

    await page.goto('/')
    await expect(replyItem(page, requestId)).toBeVisible()
    await page.waitForFunction(() => document.getAnimations().length === 0)
    await sideways()
    await shot(page, info, `n9b-home-long-link-${name}`)
    const overhang = await page.evaluate(() => {
      const card = document.querySelector('li[data-home-item^="reply:"]')?.getBoundingClientRect()
      const words = document.querySelector('li[data-home-item^="reply:"] p')?.getBoundingClientRect()
      return card && words ? words.right - card.right : 0
    })
    expect(overhang, 'the words of a reply stay inside its card').toBeLessThanOrEqual(0)

    await page.goto(`/workflows?request=${requestId}`)
    await expect(page.getByRole('article')).toBeVisible()
    await page.waitForFunction(() => document.getAnimations().length === 0)
    await expectAccessible(page, path.join(OUT, 'axe'), `request-${name}`)
    await sideways()
    await shot(page, info, `n9b-request-${name}`)

    await backend.delete('alice', `/api/v1/drafts/${draft.id}`)
    await context.close()
  })
}

const LAST_RUN = /^(?:Daily|Weekdays|Mon|Tue|Wed|Thu|Fri|Sat|Sun|No schedule)(?: \d{1,2}:\d{2})? · (?:no runs yet|last run (?:today|[A-Z][a-z]{2} \d{1,2} [A-Z][a-z]{2}(?: \d{4})?), .+)$/

/** Every second line is whole: none is cut with an ellipsis or runs past its row. It may wrap, as the sketch's rows do. */
async function lineFits(lines: Locator): Promise<{ rows: number; broken: string[] }> {
  const found = await lines.evaluateAll((els) =>
    els.map((el) => {
      const row = el.closest('li')?.getBoundingClientRect()
      return { text: el.textContent ?? '', cut: el.scrollWidth > el.clientWidth, out: row ? el.getBoundingClientRect().right > row.right : false }
    }),
  )
  return { rows: found.length, broken: found.filter((line) => line.cut || line.out).map((line) => line.text) }
}

for (const user of ['alice', 'bob']) {
  test(`${user} sees each workflow's last run on one line in its row at every width${user === 'alice' ? ', and the chat’s check card says the same' : ''}`, async ({ browser, backend }, info) => {
    const { approvalId } = await backend.waitingRun('alice')
    const quietName = `Last run lane ${randomUUID().slice(0, 6)}`
    await backend.post('alice', '/api/v1/agent-use-cases', { name: quietName, instruction: 'Check LangGraph for a new release and raise a ticket in MOCK.', agents: [{ card_id: 'crd_version_checker', values: { 'GitHub repository': 'langchain-ai/langgraph', 'Jira project': 'MOCK' } }] }, undefined, [201])
    const context = await devContext(browser, user)
    const page = await context.newPage()
    const rows = page.getByRole('list', { name: 'Workflows' }).locator('li[data-workflow-id]')
    const watchlist = rows.filter({ hasText: 'Software watchlist' })
    const lastLine = (row: Locator) => row.locator('span[class*="sub"]')
    for (const width of [1920, 1280, 1050, 900, 390]) {
      await page.setViewportSize({ width, height: 900 })
      await page.goto('/workflows')
      await expect(watchlist).toBeVisible()
      await expect(lastLine(watchlist), 'a waiting check says it waits for a yes, and is not a test run').toHaveText(/^(?:No schedule|Mon \d+:\d\d|Daily \d+:\d\d|Weekdays \d+:\d\d) · last run today, waiting for a yes$/)
      await expect(watchlist.getByText('Waiting for a yes', { exact: true })).toBeVisible()
      await expect(watchlist.getByText('Test run', { exact: true }), 'Check now is not a test run').toHaveCount(0)
      const fit = await lineFits(lastLine(rows))
      expect(fit.rows, 'every row has a last-run line').toBe(await rows.count())
      expect(fit.broken, `each row’s line is whole and inside its row at ${width} px`).toEqual([])
      for (const text of await lastLine(rows).allInnerTexts()) expect(LAST_RUN.test(text), `"${text}" is a row’s line`).toBe(true)
      await expectAccessible(page, path.join(OUT, 'axe'), `workflows-last-run-${user}-${width}`)
      await shot(page, info, `r9-workflows-${user}-${width}`)
    }

    if (user === 'alice') {
      await page.goto('/workflows')
      const before = await lastLine(watchlist).innerText()
      for (const width of [1920, 1280, 1050, 900, 390]) {
        await page.setViewportSize({ width, height: 900 })
        await page.goto('/')
        await page.getByRole('textbox').fill('Check my workflows')
        await page.keyboard.press('Enter')
        const card = page.getByRole('main').getByRole('list', { name: 'Your workflows' })
        await expect(card).toBeVisible()
        await expect(lastLine(card.locator('li[data-workflow-id]').filter({ hasText: 'Software watchlist' })), 'the check card says what the row says').toHaveText(before)
        const fit = await lineFits(lastLine(card.locator('li[data-workflow-id]')))
        expect(fit.rows, 'the card has a line for each workflow').toBeGreaterThan(0)
        expect(fit.broken, `each line in the check card is whole at ${width} px`).toEqual([])
        await shot(page, info, `r9-check-card-alice-${width}`)
      }
    }
    await context.close()
    if (user === 'alice') {
      const { digest } = await backend.get<{ digest: string }>('bob', `/api/v1/approvals/${approvalId}`)
      await backend.post('bob', `/api/v1/approvals/${approvalId}/decisions`, { step: 0, verdict: 'decline', digest })
      const again = await devContext(browser, 'alice')
      const declined = await again.newPage()
      await declined.goto('/workflows')
      const row = declined.locator('li[data-workflow-id]').filter({ hasText: 'Software watchlist' })
      await expect(lastLine(row), 'a declined run names who declined, and writes no ticket').toHaveText(/ · last run [^,]+, declined by Bob\. Nothing was written\.$/)
      await expect(row.getByText('On', { exact: true }), 'a declined run has no pill, so the workflow reads On').toBeVisible()
      expect((await lineFits(lastLine(row))).broken).toEqual([])
      await shot(declined, info, 'r9-workflows-declined')
      await again.close()
    }
  })
}
