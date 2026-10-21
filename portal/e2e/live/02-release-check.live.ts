import { expect } from '@playwright/test'
import { mkdir, stat } from 'node:fs/promises'
import path from 'node:path'
import { headline } from '../support/flows'
import { assertClean, watchPage } from '../support/test'
import { test } from './support/test'
import { CATCH_UP_MS, DESKTOP, expectCaughtUp, openContext, OUT, runExampleFromBuilder, shot, switchUser } from './support/ui'

const OWN_WORK = 'You started this run, so another Approver must decide.'

test('alice starts a release check, bob approves it on the Tracker, and one MOCK ticket is written', async ({ browser, backend }, info) => {
  const ticketsBefore = await backend.tickets()
  const context = await browser.newContext({
    viewport: DESKTOP,
    locale: 'en-SG',
    timezoneId: 'Asia/Singapore',
    recordVideo: { dir: path.join(OUT, 'results', 'video'), size: DESKTOP },
  })
  const page = await context.newPage()
  const watch = watchPage(page)
  const video = page.video()
  expect(video, 'the page is recording').not.toBeNull()

  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()

  const runId = await runExampleFromBuilder(page, info, 'success')
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  await shot(page, info, 'success-04-run-page')

  await backend.waitForState(runId, ['awaiting_approval'])
  expect((await backend.tickets()).filter((ticket) => ticket.run_id === runId), 'nothing is written while the run waits').toEqual([])
  await expect(headline(page), 'the Tracker reaches the approval gate').toHaveText('Waiting for an Approver', { timeout: CATCH_UP_MS })
  await expectCaughtUp(page)
  const approval = page.getByRole('region', { name: 'Approval' })
  await expect(approval.getByText(OWN_WORK), 'alice is told why she cannot decide').toBeVisible()
  await expect(approval.getByRole('button', { name: 'Approve', exact: true }), 'alice has no Approve button').toHaveCount(0)
  await shot(page, info, 'success-05-run-awaiting-approval')

  const phone = await openContext(browser, { phone: true })
  const phonePage = await phone.newPage()
  await phonePage.goto(`/runs/${runId}`)
  await expect(phonePage.getByRole('region', { name: 'Approval' }).getByText(OWN_WORK)).toBeVisible({ timeout: CATCH_UP_MS })
  await shot(phonePage, info, 'success-05-run-awaiting-approval-phone')
  await phone.close()

  const approvalId = await backend.approvalIdOf(runId)
  const [message] = (await backend.teamsMessages()).filter((entry) => entry.approval_id === approvalId)
  expect(message, 'the Teams stub holds the approval card').toBeDefined()
  expect(message?.link, 'the card links to the approval page').toMatch(new RegExp(`/approvals/${approvalId}$`))

  await page.getByRole('link', { name: 'Teams', exact: true }).first().click()
  await expect(page).toHaveURL(/\/teams$/)
  const card = page.locator('article', { has: page.locator(`a[href$="/approvals/${approvalId}"]`) })
  await expect(card, 'the card shows the backend message').toContainText(message?.text ?? '')
  await expect(card, 'the card says which run it belongs to').toContainText(/Started by Alice, /)
  await expect(card, 'the card says the approval is still waiting').toContainText('Waiting for an Approver')
  await shot(page, info, 'success-06-teams-card')
  await page.locator(`a[href$="/approvals/${approvalId}"]`).click()
  await expect(page).toHaveURL(new RegExp(`/approvals/${approvalId}$`))

  const refusal = await page.request.post(`/api/v1/approvals/${approvalId}/decisions`, {
    headers: { 'X-Dev-User': 'alice' },
    data: { step: 0, verdict: 'approve', digest: (await backend.get<{ digest: string }>('alice', `/api/v1/approvals/${approvalId}`)).digest },
  })
  expect(refusal.status(), 'the backend refuses alice').toBe(403)
  const own = (await refusal.json()) as { refusal: string; message: string }
  expect(own.refusal).toBe('own_work')
  await expect(page.getByText(own.message).first(), 'the page says what the backend says').toBeVisible()
  await expect(page.getByRole('button', { name: /^Approve/ }), 'alice has no approve button').toHaveCount(0)
  await shot(page, info, 'success-07-approval-alice-refused')
  expect((await backend.run(runId)).state, 'the refused attempt did not move the run').toBe('awaiting_approval')

  await page.getByRole('link', { name: 'Watch the run' }).click()
  await expect(page).toHaveURL(new RegExp(`/runs/${runId}$`))
  await switchUser(page, 'Bob')
  const proposed = (await backend.get<{ actions: { fields: { title: string; body: string } }[] }>('bob', `/api/v1/approvals/${approvalId}`)).actions
  expect(proposed, 'one write is proposed').toHaveLength(1)
  const { title, body } = proposed[0]?.fields ?? { title: '', body: '' }
  await expect(approval.getByText(title, { exact: true }), 'bob sees the exact ticket title').toBeVisible({ timeout: CATCH_UP_MS })
  // The panel shows the body one paragraph to an element, split where the backend's text has a blank line.
  for (const paragraph of body.split(/\n{2,}/)) {
    await expect(approval.getByText(paragraph.replace(/\s+/g, ' ').trim(), { exact: true }), 'bob sees the exact ticket body').toBeVisible()
  }
  const approve = approval.getByRole('button', { name: 'Approve', exact: true })
  await expect(approve).toBeVisible()
  await shot(page, info, 'success-08-run-bob-can-decide')
  await approve.click()

  const finished = await backend.waitForState(runId, ['succeeded'])
  expect(finished.outcome).toBe('written')
  const written = (await backend.tickets()).filter((ticket) => ticket.run_id === runId)
  expect(written, 'exactly one ticket for this run').toHaveLength(1)
  const key = written[0]?.key ?? ''
  expect(key).toMatch(/^MOCK-\d+$/)
  expect(written[0]?.title).toBe(title)
  expect((await backend.tickets()).length - ticketsBefore.length, 'one ticket more than before the run').toBe(1)
  await expect(headline(page), 'the Tracker ends on the ticket key').toHaveText(`${key} is in Jira`, { timeout: CATCH_UP_MS })
  await shot(page, info, 'success-09-run-written')

  await page.getByRole('link', { name: 'Jira', exact: true }).first().click()
  await expect(page).toHaveURL(/\/jira$/)
  await expect(page.getByText(key, { exact: true }), 'mock Jira lists the ticket once').toHaveCount(1)
  await expect(page.getByText(title).first()).toBeVisible()
  await shot(page, info, 'success-10-jira-ticket')

  await page.getByRole('link', { name: 'Teams', exact: true }).first().click()
  await expect(
    page.locator('article', { has: page.locator(`a[href$="/approvals/${approvalId}"]`) }),
    'the Teams card now says who approved',
  ).toContainText('Approved by Bob')
  await shot(page, info, 'success-11-teams-card-approved')

  assertClean(watch)
  await mkdir(path.join(OUT, 'video'), { recursive: true })
  const target = path.join(OUT, 'video', 'success-path.webm')
  await context.close()
  await video?.saveAs(target)
  expect((await stat(target)).size, 'the video file is not empty').toBeGreaterThan(50_000)
})
