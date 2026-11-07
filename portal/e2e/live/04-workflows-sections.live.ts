import { randomUUID } from 'node:crypto'
import path from 'node:path'
import type { Page } from '@playwright/test'
import { expectAccessible } from '../support/axe'
import { assertClean, watchPage } from '../support/test'
import type { Backend } from './support/stack'
import { expect, test } from './support/test'
import { devContext, OUT, shot } from './support/ui'

const replyItem = (page: Page, requestId: string) => page.locator(`li[data-home-item="reply:${requestId}"]`)
const followingRow = (page: Page, requestId: string) => page.locator(`li[data-request="${requestId}"]`)
const draftRow = (page: Page, draftId: string) => page.locator(`li[data-draft="${draftId}"]`)
const menu = (page: Page) => page.getByRole('navigation', { name: 'Main' }).filter({ visible: true })
const countOnTab = async (page: Page): Promise<number> => {
  const name = (await menu(page).getByRole('link', { name: /^Workflows(, \d+ need you)?$/ }).getAttribute('aria-label')) ?? 'Workflows'
  return Number(/(\d+) need you/.exec(name)?.[1] ?? 0)
}
const countInHeading = async (page: Page): Promise<number> => {
  const heading = page.getByRole('main').getByRole('heading', { level: 2, name: /^Needs you/ })
  return (await heading.count()) === 0 ? 0 : Number((await heading.innerText()).replace(/\D/g, ''))
}

interface Made {
  readonly requestId: string
  readonly note: string
}

const LONG_LINK = `https://example.com/${'long-link-without-a-break-'.repeat(8)}`

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
  await expect(replyItem(page, requestId)).toContainText('Not on the plan yet')
  const before = await countInHeading(page)
  expect(await countOnTab(page), 'the tab and Needs you agree').toBe(before)
  await expect(followingRow(page, requestId)).toContainText(note)
  await shot(page, info, 'n9b-asker-needs-you')

  await replyItem(page, requestId).getByRole('link', { name: 'Read the reply' }).click()
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
  expect(await countOnTab(page), 'the tab and Needs you still agree').toBe(await countInHeading(page))
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

test('alice sees the run she started under Waiting on others on Workflows, and not on Home', async ({ browser, backend }) => {
  const { runId } = await backend.waitingRun('alice')
  const context = await devContext(browser, 'alice')
  const page = await context.newPage()
  await page.goto('/workflows')
  await expect(page.getByRole('region', { name: 'Waiting on others' }).locator(`a[href="/runs/${runId}"]`)).toContainText('You started it')
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 2, name: /Needs you|All quiet|Start your first/ }).first()).toBeVisible()
  await expect(page.getByRole('region', { name: 'Waiting on others' })).toHaveCount(0)
  await expect(page.locator(`[data-waiting="${runId}"]`)).toHaveCount(0)
  await context.close()
})

test('alice discards a draft by keyboard, after a question that says what is lost, and Undo puts it back', async ({ browser, backend }, info) => {
  const draft = await draftFor(backend, 'keys')
  const context = await devContext(browser, 'alice')
  const page = await context.newPage()
  await page.goto('/workflows')
  const row = draftRow(page, draft.id)
  await expect(row).toContainText(draft.name)
  const kept = (await backend.get<{ drafts: { draft_id: string; created_at: string; saved_at: string }[] }>('alice', '/api/v1/drafts')).drafts.find((item) => item.draft_id === draft.id)
  expect(kept, 'the draft is saved before it is discarded').toBeDefined()
  await row.getByRole('link', { name: `Resume ${draft.name}` }).focus()
  await page.keyboard.press('Tab')
  await expect(row.getByRole('button', { name: `Discard ${draft.name}` })).toBeFocused()
  await page.keyboard.press('Enter')
  const dialog = page.getByRole('alertdialog', { name: `Discard ${draft.name}?` })
  await expect(dialog).toBeVisible()
  await expect(dialog).toContainText('Nothing has run, and nothing changes in Jira or Teams')
  await expect(dialog.getByRole('button', { name: 'Keep the draft' })).toBeFocused()
  await shot(page, info, 'n9b-discard-asks')

  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  await expect(row, 'asking and then backing out keeps the draft').toBeVisible()

  await row.getByRole('button', { name: `Discard ${draft.name}` }).focus()
  await page.keyboard.press('Enter')
  await expect(dialog).toBeVisible()
  await page.keyboard.press('Tab')
  await expect(dialog.getByRole('button', { name: 'Discard draft' })).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(page.getByText(`Discarded ${draft.name}.`).last()).toBeVisible()
  await expect(page.getByRole('button', { name: 'Undo' })).toBeFocused()
  await expect(row).toHaveCount(0)
  const gone = await backend.get<{ drafts: { draft_id: string }[] }>('alice', '/api/v1/drafts')
  expect(gone.drafts.map((item) => item.draft_id)).not.toContain(draft.id)
  await shot(page, info, 'n9b-discarded')

  await page.keyboard.press('Enter')
  await expect(row).toBeVisible()
  await expect(page.getByText('Put back.').last()).toBeVisible()
  await expect(row.getByRole('link', { name: `Resume ${draft.name}` }), 'focus moves to the restored draft').toBeFocused()
  const back = await backend.get<{ drafts: { draft_id: string; created_at: string; saved_at: string; content: { name?: string } }[] }>('alice', '/api/v1/drafts')
  const again = back.drafts.find((item) => item.draft_id === draft.id)
  expect(again?.content.name, 'Undo saved the same draft').toBe(draft.name)
  expect([again?.created_at, again?.saved_at], 'Undo keeps the times, so Last saved stays true').toEqual([kept?.created_at, kept?.saved_at])
  await backend.delete('alice', `/api/v1/drafts/${draft.id}`)
  await context.close()
})

test('the search and the filters stay hidden until the search button is pressed', async ({ browser, backend }, info) => {
  await backend.waitingRun('alice')
  const context = await devContext(browser, 'alice')
  const page = await context.newPage()
  await page.goto('/workflows')
  const search = page.getByRole('button', { name: 'Search workflows' })
  await expect(page.getByRole('searchbox', { name: 'Find a workflow' })).toHaveCount(0)
  await expect(page.getByRole('group', { name: 'Show' })).toHaveCount(0)
  await expect(page.getByRole('main').locator('li[data-workflow-id] [data-state]')).toHaveCount(0)
  await search.scrollIntoViewIfNeeded()
  await shot(page, info, 'n9b-search-hidden')
  await search.focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('searchbox', { name: 'Find a workflow' })).toBeFocused()
  await expect(page.getByRole('button', { name: 'Stopped', exact: true })).toBeVisible()
  await shot(page, info, 'n9b-search-open')
  await page.getByRole('button', { name: 'Hide search' }).click()
  await expect(page.getByRole('searchbox', { name: 'Find a workflow' })).toHaveCount(0)
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
    await expect(page.getByRole('region', { name: 'Waiting on others' })).toBeVisible()
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
