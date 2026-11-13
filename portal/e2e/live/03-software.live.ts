import type { Page } from '@playwright/test'
import type { Backend } from './support/stack'
import { assertClean, watchPage } from '../support/test'
import { expectAccessible } from '../support/axe'
import { expect, test } from './support/test'
import { decline, devContext, expectReadOnly, OUT, shot } from './support/ui'
import path from 'node:path'

const countLine = (page: Page) => page.locator('main h1 + p')

/** A software's own page is at /software/{id}. */
async function softwareId(backend: Backend, name: string): Promise<string> {
  const { watchlist } = await backend.get<{ watchlist: { software: { id: string; name: string }[] } }>('alice', '/api/v1/watchlist')
  return watchlist.software.find((item) => item.name === name)?.id ?? ''
}
const listRow = (page: Page, name: string) => page.locator('li[data-status]').filter({ hasText: name })

// A moved or missing repository stays in Operators' Needs you on Home and Workflows, so these tests leave no software behind for the lanes after them.
test.afterEach(async ({ backend }) => {
  await backend.freshWatchlist('alice', [])
})

test('alice adds software by its name: Find it, a checked guess with where it came from, and the row starts at Not known', async ({ browser, backend }, info) => {
  await backend.freshWatchlist('alice', [])
  const context = await devContext(browser, 'alice')
  const page = await context.newPage()
  const watch = watchPage(page)
  await page.goto('/software')
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Watchlist')
  await expect(page.getByRole('heading', { level: 2 })).toHaveText([/^How it’s checked/])
  await shot(page, info, 'n21-03-name')

  await page.getByLabel('Software name').fill('  LangGraph ')
  await page.getByRole('button', { name: 'Find it' }).click()
  await expect(page.getByRole('heading', { name: 'Adding LangGraph' })).toBeFocused()
  const form = page.locator('form[aria-labelledby="sw-guess"]')
  await expect(form).toContainText('langchain-ai/langgraph')
  await expect(form).toContainText('From our list of known projects.')
  await expect(form).toContainText('Checked just now. The project is on GitHub and its newest release is 1.2.16.')
  await expect(form.getByLabel(/^Version we run/)).toHaveValue('')
  await expectAccessible(page, path.join(OUT, 'axe'), 'n21-software-guess')
  await shot(page, info, 'n21-03-guess')

  await page.getByRole('button', { name: 'Looks right, add it' }).click()
  const row = listRow(page, 'LangGraph')
  await expect(row).toContainText('Watching')
  await expect(row).toContainText('Added today')
  await expect(countLine(page), 'the count line counts the new row').toHaveText('1 watching')
  await expect(page.getByRole('status').filter({ hasText: 'Added LangGraph' })).toBeVisible()
  await shot(page, info, 'n21-03-added')

  await page.getByRole('button', { name: 'Check now' }).click()
  await expect(page).toHaveURL(/\/runs\/[^/]+$/)
  const runId = page.url().split('/').at(-1) ?? ''
  await backend.waitForState(runId, ['succeeded'])
  await page.goto('/software')
  await expect(row).not.toContainText('Added today', { timeout: 30_000 })
  await expect(row).toContainText('Newest is 1.2.16')
  await expect(row).toContainText('Watching')
  await expect(row).not.toContainText('Up to date')
  await expect(countLine(page), 'with no version to be up to date with, the count line never says up to date').toHaveText('1 watching')
  await row.getByRole('link').click()
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('LangGraph')
  await expect(page.getByRole('main')).toContainText(/You run\s*Not known/)
  await expect(page.getByRole('main')).toContainText('newer than 1.2.16, the newest the first check read')
  await expect(page.getByRole('main')).not.toContainText('Up to date')
  await shot(page, info, 'n21-03-checked')
  assertClean(watch)
  await context.close()
})

test('several matches: alice chooses between Terraform and OpenTofu, and is told when she has not chosen', async ({ browser, backend }, info) => {
  await backend.freshWatchlist('alice', [])
  const context = await devContext(browser, 'alice')
  const page = await context.newPage()
  const watch = watchPage(page)
  await page.goto('/software')
  await page.getByLabel('Software name').fill('Terraform')
  await page.getByRole('button', { name: 'Find it' }).click()
  const form = page.locator('form[aria-labelledby="sw-guess"]')
  await expect(form.getByRole('group', { name: 'Which one do you mean?' })).toBeVisible()
  await expect(form.getByRole('radio')).toHaveCount(2)
  await expect(form.getByRole('radio', { checked: true })).toHaveCount(0)
  await shot(page, info, 'n21-03-choose')

  await form.getByRole('button', { name: 'Add Terraform' }).click()
  await expect(page.getByRole('alert').filter({ hasText: 'Choose one project first' })).toBeVisible()
  await expect(page.locator('li[data-status]')).toHaveCount(0)

  await form.getByRole('radio', { name: /opentofu\/opentofu/ }).check()
  await form.getByRole('button', { name: 'Add Terraform' }).click()
  const row = listRow(page, 'Terraform')
  await expect(row).toBeVisible()
  await row.getByRole('link').click()
  await expect(page.getByRole('main')).toContainText('github.com/opentofu/opentofu')
  assertClean(watch)
  await context.close()
})

test('a name the list lacks says so plainly and falls back to the GitHub address, and a name of spaces is refused', async ({ browser, backend }, info) => {
  await backend.freshWatchlist('alice', [])
  const context = await devContext(browser, 'alice')
  const page = await context.newPage()
  const watch = watchPage(page)
  await page.goto('/software')

  await page.getByLabel('Software name').fill('     ')
  await page.getByRole('button', { name: 'Find it' }).click()
  await expect(page.getByText('Give the software a name.')).toBeVisible()
  await expect(page.getByLabel('Software name')).toBeFocused()

  await page.getByLabel('Software name').fill('Zorblax')
  await page.getByRole('button', { name: 'Find it' }).click()
  await expect(page.getByRole('heading', { name: 'I couldn’t find “Zorblax”' })).toBeFocused()
  await expect(page.getByText(/I don.t know a GitHub project called Zorblax/)).toBeVisible()
  await shot(page, info, 'n21-03-not-known')
  await page.getByLabel('GitHub repository').fill('https://github.com/fastapi/fastapi')
  await page.getByLabel(/^Version we run/).fill('0.115.0')
  await page.getByRole('button', { name: 'Add Zorblax' }).click()
  const row = listRow(page, 'Zorblax')
  await expect(row).toContainText('Watching')
  await row.getByRole('link').click()
  await expect(page.getByRole('main')).toContainText('github.com/fastapi/fastapi')
  await expect(page.getByRole('main')).toContainText(/You run\s*0.115.0/)
  assertClean(watch)
  await context.close()
})

test('a project the watchlist already holds is named, and a prefixed tag such as n8n@2.4.2 counts as a release', async ({ browser, backend }) => {
  await backend.freshWatchlist('alice', [{ name: 'Our agents', repo: 'langchain-ai/langgraph', our_version: '1.2.14' }])
  const context = await devContext(browser, 'alice')
  const page = await context.newPage()
  const watch = watchPage(page)
  await page.goto('/software')

  await page.getByLabel('Software name').fill('Our agents')
  await page.getByRole('button', { name: 'Find it' }).click()
  await expect(page.getByText('Our agents is already on the list.')).toBeVisible()

  await page.getByLabel('Software name').fill('LangGraph')
  await page.getByRole('button', { name: 'Find it' }).click()
  await expect(page.getByText('langchain-ai/langgraph is already on the list as Our agents.').first()).toBeVisible()
  await expect(page.getByRole('button', { name: 'Looks right, add it' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: /^Add / })).toHaveCount(0)
  await page.getByRole('link', { name: 'Show it on the list' }).click()
  await expect(page).toHaveURL(/\/software\/[^/]+$/)
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Our agents')
  await page.goto('/software')

  await page.getByLabel('Software name').fill('n8n')
  await page.getByRole('button', { name: 'Find it' }).click()
  await expect(page.getByText('its newest release is n8n@2.4.2')).toBeVisible()
  assertClean(watch)
  await context.close()
})

test('a project that publishes no releases is not added: it says why and offers only Change and Start again', async ({ browser, backend }, info) => {
  await backend.freshWatchlist('alice', [])
  const context = await devContext(browser, 'alice')
  const page = await context.newPage()
  const watch = watchPage(page)
  await page.goto('/software')
  await page.getByLabel('Software name').fill('Python')
  await page.getByRole('button', { name: 'Find it' }).click()
  const form = page.locator('form[aria-labelledby="sw-guess"]')
  await expect(form).toContainText('python/cpython doesn’t publish releases on GitHub, which is the only place this check reads. It can’t be watched here.')
  await expect(form.getByRole('button')).toHaveText(['Change', 'Start again'])
  await expect(form.getByLabel(/^Version we run/)).toHaveCount(0)
  await shot(page, info, 'n21-03-no-releases')
  await form.getByRole('button', { name: 'Change' }).click()
  await expect(form.getByLabel('GitHub repository')).toHaveValue('')
  await expect(page.locator('li[data-status]')).toHaveCount(0)
  assertClean(watch)
  await context.close()
})

test('while a yes waits, one bar decides the check, every row stays in the list and the count is the real number', async ({ browser, backend }, info) => {
  await backend.waitingRun('alice', [
    { name: 'LangGraph', repo: 'langchain-ai/langgraph', our_version: '1.2.14' },
    { name: 'Redis', repo: 'redis/redis', our_version: '8.0.0' },
  ])
  const alice = await devContext(browser, 'alice')
  const page = await alice.newPage()
  const watch = watchPage(page)
  await page.goto('/software')
  const attention = page.getByRole('region', { name: /^Needs attention/ })
  await expect(attention).toContainText('The latest check wants to raise 2 upgrade tickets.')
  await expect(attention).toContainText('Waiting for another Approver. This check is your own work.')
  await expect(attention.getByRole('link', { name: 'Review and decide' })).toHaveCount(0)
  await expect(page.getByRole('region', { name: 'Software we watch' }).locator('li')).toHaveCount(2)
  await expect(page.locator('li[data-status="awaiting_approval"]')).toHaveCount(2)
  await expect(page.getByRole('button', { name: 'Check now' })).not.toHaveClass(/primary/)
  await shot(page, info, 'n21-03-waiting-alice')
  assertClean(watch)
  await alice.close()

  const bob = await devContext(browser, 'bob')
  const bobPage = await bob.newPage()
  await bobPage.goto('/software')
  await expect(bobPage.getByRole('region', { name: /^Needs attention/ }).getByRole('link', { name: 'Review and decide' })).toHaveCount(1)
  await expect(bobPage.getByRole('region', { name: 'Software we watch' }).locator('li')).toHaveCount(2)
  await shot(bobPage, info, 'n21-03-waiting-bob')
  await bob.close()
})

test('the count line and what checks each row hold through a decline, and the declined check’s record is on the row and in its History, as Alice and Bob', async ({ browser, backend }, info) => {
  const { runId, approvalId } = await backend.waitingRun('alice', [
    { name: 'LangGraph', repo: 'langchain-ai/langgraph', our_version: '1.2.14' },
    { name: 'Redis', repo: 'redis/redis', our_version: '8.0.0' },
    { name: 'LangServe', repo: 'langchain-ai/langserve', our_version: '0.3.1' },
  ])
  const LINE = '2 have a newer version · 1 can’t be found'
  const before = await devContext(browser, 'alice')
  const waiting = await before.newPage()
  await waiting.goto('/software')
  await expect(waiting.locator('li[data-status="awaiting_approval"]'), 'both upgrades wait for a yes').toHaveCount(2)
  await expect(countLine(waiting), 'a row whose ticket waits for a yes still has a newer version').toHaveText(LINE)
  await before.close()

  await backend.send('PUT', 'alice', '/api/v1/watchlist/schedule', { day: 'monday', at: '09:00' })
  const { digest } = await backend.get<{ digest: string }>('bob', `/api/v1/approvals/${approvalId}`)
  await backend.post('bob', `/api/v1/approvals/${approvalId}/decisions`, { step: 0, verdict: 'decline', digest, reason: 'Wrong version' }, undefined, [201])
  await backend.waitForState(runId, ['rejected'])
  const record = 'Declined by Bob. Nothing was written. Reason: Wrong version. The tickets will be proposed again at the next check, '

  for (const user of ['alice', 'bob']) {
    for (const width of [1920, 1280, 900, 390]) {
      const context = await devContext(browser, user, { phone: width === 390 })
      const page = await context.newPage()
      if (width !== 390) await page.setViewportSize({ width, height: 1000 })
      const watch = watchPage(page)
      await page.goto('/software')
      await expect(countLine(page), 'the count line is the same after the decline').toHaveText(LINE)
      const row = listRow(page, 'LangGraph')
      await expect(row, 'each row names what checks it').toContainText('checked by Software watchlist')
      await expect(row).toContainText('Newer out')
      await row.getByRole('link').click()
      await expect(page.getByRole('main')).toContainText('Upgrade ticket')
      await expect(page.getByRole('main')).toContainText(record)
      await page.getByRole('button', { name: 'History of LangGraph' }).click()
      const history = page.getByRole('list', { name: 'History of LangGraph' })
      await expect(history, 'LangGraph’s history gives the record').toContainText(`Found 1.2.16. ${record}`)
      await expect(page.locator('main a[href*="/jira/"]'), 'no ticket link on a declined software').toHaveCount(0)
      await history.scrollIntoViewIfNeeded()
      await shot(page, info, `r15-declined-history-${user}-${String(width)}`)
      await page.goto('/software')
      await listRow(page, 'LangServe').getByRole('link').click()
      await expect(page.getByRole('main'), 'only a software with a new version gives the record').not.toContainText('Declined by')
      await page.goto('/software')
      await shot(page, info, `r15-count-line-${user}-${String(width)}`)
      assertClean(watch)
      await context.close()
    }
  }
})

test('an Approver who is not an Operator sees the list but no way to add', async ({ browser, backend }) => {
  await backend.freshWatchlist('alice', [{ name: 'LangGraph', repo: 'langchain-ai/langgraph', our_version: '1.2.14' }])
  const context = await devContext(browser, 'bob')
  const page = await context.newPage()
  await page.goto('/software')
  await expect(page.getByText('LangGraph').first()).toBeVisible()
  await expect(page.getByLabel('Software name')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Find it' })).toHaveCount(0)
  for (const name of ['Check now', 'Remove', 'Change schedule', 'Set a schedule', 'Turn off schedule']) await expect(page.getByRole('button', { name })).toHaveCount(0)
  await expectReadOnly(page, 'the watchlist')
  await context.close()
})

const FASTAPI_OLD = { name: 'FastAPI', repo: 'tiangolo/fastapi', our_version: '0.115.0' }
const MOVED_WORDS = 'GitHub now calls this project fastapi/fastapi. We saved tiangolo/fastapi, and checks still reach it through GitHub’s redirect.'

for (const phone of [false, true]) {
  const width = phone ? '390' : '1440'

  test(`GitHub renamed a watched repository: the row, the ticket and the approval name it, an Operator switches by keyboard with Undo, and the next check uses the new address (${width})`, async ({ browser, backend }, info) => {
    await backend.freshWatchlist('alice', [FASTAPI_OLD])
    const alice = await devContext(browser, 'alice', { phone })
    const page = await alice.newPage()
    const watch = watchPage(page)
    await page.goto('/software')
    const row = listRow(page, 'FastAPI')
    await expect(row).not.toContainText('GitHub now calls')
    await expect(page.getByRole('button', { name: /^Use the new address/ })).toHaveCount(0)
    const fastapi = await softwareId(backend, 'FastAPI')
    const itemPage = `/software/${fastapi}`

    await page.getByRole('button', { name: 'Check now' }).click()
    await expect(page).toHaveURL(/\/runs\/[^/]+$/)
    const runId = page.url().split('/').at(-1) ?? ''
    await backend.waitForState(runId, ['awaiting_approval'])
    const approvalId = await backend.approvalIdOf(runId)

    await page.goto('/software')
    const attention = page.getByRole('region', { name: /^Needs attention/ })
    await expect(attention).toContainText('GitHub moved FastAPI from tiangolo/fastapi to fastapi/fastapi.')
    await expect(page.getByRole('button', { name: /^Use the new address/ }), 'the list offers no new address').toHaveCount(0)
    await attention.getByRole('link', { name: /^Open it/ }).click()
    await expect(page).toHaveURL(new RegExp(`/software/${fastapi}$`))
    const item = page.getByRole('main')
    await expect(item).toContainText(MOVED_WORDS)
    await expect(item).toContainText('tiangolo/fastapi')
    await expect(page.getByRole('button', { name: /^Use the new address/ })).toHaveCount(1)
    await expectAccessible(page, path.join(OUT, 'axe'), `n21b-moved-${width}`)
    await shot(page, info, `n21b-04-moved-${width}`)
    if (phone) expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth), 'no sideways scroll at 390 px').toBe(true)

    const fastapiId = (await backend.get<{ watchlist: { software: { id: string }[] } }>('alice', '/api/v1/watchlist')).watchlist.software[0]?.id ?? ''
    await page.goto('/')
    const onHome = page.locator(`[data-home-item="address:${fastapiId}"]`)
    await expect(onHome).toContainText('GitHub moved FastAPI from tiangolo/fastapi to fastapi/fastapi.')
    await onHome.getByRole('link', { name: 'Show it on the watchlist' }).click()
    await expect(page).toHaveURL(new RegExp(`/software/${fastapiId}$`))
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('FastAPI')
    await page.goto('/workflows')
    await expect(page.locator(`[data-home-item="address:${fastapiId}"]`)).toHaveCount(1)
    await page.locator(`[data-home-item="address:${fastapiId}"] a`).click()
    await expect(page).toHaveURL(new RegExp(`/software/${fastapiId}$`))

    const forBob = await backend.get<{ actions: { fields: { title: string; body: string } }[] }>('bob', `/api/v1/approvals/${approvalId}`)
    const ticketBody = forBob.actions[0]?.fields.body ?? ''
    expect(ticketBody).toContain('(tiangolo/fastapi, which GitHub now calls fastapi/fastapi)')

    // The keyboard: Enter asks, Escape cancels and gives focus back, Enter asks again, Tab reaches Yes.
    const versionBefore = (await backend.get<{ watchlist: { version: number } }>('alice', '/api/v1/watchlist')).watchlist.version
    const ask = page.getByRole('button', { name: 'Use the new address for FastAPI' })
    await ask.focus()
    await page.keyboard.press('Enter')
    const question = page.locator('[id^="new-address-question-"]')
    await expect(question).toBeFocused()
    await expect(question).toHaveText('Read FastAPI from fastapi/fastapi from now on? Only our list changes. Nothing is written to GitHub or Jira.')
    await shot(page, info, `n21b-04-confirm-${width}`)
    await page.keyboard.press('Escape')
    await expect(ask).toBeFocused()
    await expect(item).toContainText('tiangolo/fastapi')
    expect((await backend.get<{ watchlist: { version: number } }>('alice', '/api/v1/watchlist')).watchlist.version, 'cancelling saved nothing').toBe(versionBefore)
    await page.keyboard.press('Enter')
    await expect(question).toBeFocused()
    await page.keyboard.press('Tab')
    await expect(page.getByRole('button', { name: 'Yes, use fastapi/fastapi' })).toBeFocused()
    await page.keyboard.press('Enter')

    const notice = page.locator('#change-notice')
    await expect(notice).toContainText('FastAPI is now read from fastapi/fastapi. Press Check now to check it.')
    await expect(page.getByRole('button', { name: 'Undo' })).toBeFocused()
    await expect(item).toContainText('github.com/fastapi/fastapi')
    await expect(item).not.toContainText('GitHub now calls')
    await expect(item).not.toContainText('tiangolo/fastapi')
    await shot(page, info, `n21b-04-switched-${width}`)

    await page.keyboard.press('Enter')
    await expect(notice).toContainText('Put back. FastAPI is read from tiangolo/fastapi again.')
    await expect(page.locator(`#software-${fastapi}`)).toBeFocused()
    await expect(item).toContainText(MOVED_WORDS)
    await ask.focus()
    await page.keyboard.press('Enter')
    await page.keyboard.press('Tab')
    await page.keyboard.press('Enter')
    await expect(notice).toContainText('FastAPI is now read from fastapi/fastapi.')
    await page.getByRole('button', { name: /^History/ }).click()
    const history = page.getByRole('list', { name: 'History of FastAPI' })
    await expect(history).toContainText('Alice used the new address fastapi/fastapi. It was tiangolo/fastapi.')
    await expect(history).toContainText('Alice put the address back to tiangolo/fastapi. It was fastapi/fastapi.')
    const saved = await backend.get<{ watchlist: { software: { source: { ref: string } }[] } }>('alice', '/api/v1/watchlist')
    expect(saved.watchlist.software.map((item) => item.source.ref)).toEqual(['fastapi/fastapi'])

    // Nothing was written outside our list: the only ticket is still waiting for a yes.
    expect((await backend.tickets()).filter((ticket) => ticket.run_id === runId)).toEqual([])

    const bob = await devContext(browser, 'bob', { phone })
    const bobPage = await bob.newPage()
    await bobPage.goto(`/approvals/${approvalId}`)
    await expect(bobPage.getByRole('main')).toContainText('tiangolo/fastapi, which GitHub now calls fastapi/fastapi')
    await decline(bobPage)
    await expect(bobPage.getByRole('heading', { level: 1 })).toHaveText('Declined, nothing was written', { timeout: 60_000 })
    await bob.close()

    await page.goto('/software')
    await page.getByRole('button', { name: 'Check now' }).click()
    await expect(page).toHaveURL(/\/runs\/[^/]+$/)
    const next = page.url().split('/').at(-1) ?? ''
    expect(next).not.toBe(runId)
    await backend.waitForState(next, ['awaiting_approval'])
    const later = await backend.get<{ actions: { fields: { body: string } }[] }>('bob', `/api/v1/approvals/${await backend.approvalIdOf(next)}`)
    const laterBody = later.actions[0]?.fields.body ?? ''
    expect(laterBody, 'the next check read the new address').toContain('on GitHub (fastapi/fastapi) newer than our version 0.115.0')
    expect(laterBody).not.toContain('tiangolo')
    await page.goto(itemPage)
    await expect(page.getByRole('main')).toContainText('github.com/fastapi/fastapi')
    await expect(page.getByRole('main')).not.toContainText('GitHub now calls')
    await page.goto('/software')
    await expect(page.getByRole('region', { name: /^Needs attention/ }).filter({ hasText: 'GitHub moved' })).toHaveCount(0)
    await shot(page, info, `n21b-04-next-check-${width}`)
    assertClean(watch)
    await alice.close()
  })

  test(`a repository GitHub cannot find says so, offers no new address and keeps Remove; an Approver sees the words and no buttons (${width})`, async ({ browser, backend }, info) => {
    await backend.freshWatchlist('alice', [
      { name: 'LangGraph', repo: 'langchain-ai/langgraph', our_version: '1.2.16' },
      { name: 'LangServe', repo: 'langchain-ai/langserve', our_version: '0.3.1' },
    ])
    const alice = await devContext(browser, 'alice', { phone })
    const page = await alice.newPage()
    const watch = watchPage(page)
    await page.goto('/software')
    await page.getByRole('button', { name: 'Check now' }).click()
    await expect(page).toHaveURL(/\/runs\/[^/]+$/)
    const runId = page.url().split('/').at(-1) ?? ''
    await backend.waitForState(runId, ['succeeded'])
    await page.goto('/software')
    await expect(listRow(page, 'LangServe')).toContainText('Can’t find')
    const attention = page.getByRole('region', { name: /^Needs attention/ })
    await expect(attention).toContainText('GitHub can’t find langchain-ai/langserve, the address saved for LangServe.')
    await attention.getByRole('link', { name: /^Open it/ }).focus()
    await page.keyboard.press('Enter')
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('LangServe')
    const item = page.getByRole('main')
    await expect(item).toContainText('GitHub can’t find langchain-ai/langserve. It may have moved to another repository. LangServe stays Can’t check until GitHub finds that address. Remove it and add it again at its new address.')
    await expect(item).not.toContainText('GitHub answered 404')
    await expect(page.getByRole('button', { name: /^Use the new address/ })).toHaveCount(0)
    await expect(page.getByRole('button', { name: /^Remove from watchlist/ })).toBeVisible()
    await expectAccessible(page, path.join(OUT, 'axe'), `n21b-not-found-${width}`)
    await shot(page, info, `n21b-04-not-found-${width}`)
    if (phone) expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth), 'no sideways scroll at 390 px').toBe(true)

    const bob = await devContext(browser, 'bob', { phone })
    const bobPage = await bob.newPage()
    await bobPage.goto(page.url())
    await expect(bobPage.getByRole('main')).toContainText('An Operator can fix this.')
    await expect(bobPage.getByRole('button', { name: /^(Use the new address|Remove)/ })).toHaveCount(0)
    await bob.close()
    assertClean(watch)
    await alice.close()
  })
}

test('an Approver sees that GitHub renamed a repository and that an Operator can switch it, with no button', async ({ browser, backend }) => {
  await backend.freshWatchlist('alice', [FASTAPI_OLD])
  await backend.checkNow('alice', (await backend.get<{ watchlist: { use_case_id: string } }>('alice', '/api/v1/watchlist')).watchlist.use_case_id).then((runId) => backend.waitForState(runId, ['awaiting_approval']))
  const bob = await devContext(browser, 'bob')
  const page = await bob.newPage()
  await page.goto(`/software/${await softwareId(backend, 'FastAPI')}`)
  const row = page.getByRole('main')
  await expect(row).toContainText(MOVED_WORDS)
  await expect(row).toContainText('An Operator can switch it to the new address.')
  await expect(page.getByRole('button', { name: /^Use the new address/ })).toHaveCount(0)
  const answer = await backend.send('POST', 'bob', `/api/v1/watchlist/software/${(await backend.get<{ watchlist: { software: { id: string }[] } }>('alice', '/api/v1/watchlist')).watchlist.software[0]?.id}/address`, { repo: 'fastapi/fastapi' })
  expect(answer.status, 'an Approver who is not an Operator is refused by the platform too').toBe(403)
  await bob.close()
})
