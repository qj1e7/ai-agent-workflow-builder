import type { Page } from '@playwright/test'
import { advance, advanceUntil, openFrozen } from './support/clock'
import { headline, lineEnded, waitingForApprover } from './support/flows'
import { expectEndsAboveTheFold, expectFitsTheFold } from './support/fold'
import { switchUser } from './support/people'
import { record } from './support/record'
import { isDesktop } from './support/states'
import { expect, test } from './support/test'

const OWN_WORK = 'You started this run, so another Approver must decide.'

test('the overview shows each stage of the live success run', async ({ page }, info) => {
  const desktop = isDesktop(info.project.name)
  await openFrozen(page, '/')
  if (desktop) await expectFitsTheFold(page, 'earlier-title')
  await record(page, info, 'overview-load')

  await advance(page, 4_000)
  await record(page, info, 'overview-mid-run')

  await advanceUntil(page, waitingForApprover(page))
  await expect(headline(page)).toHaveText('Waiting for an Approver')
  const approval = page.getByRole('region', { name: 'Approval' })
  const ownWork = approval.getByText(OWN_WORK)
  // The approval record renders on the page's frozen clock, so the clock moves until the panel has it.
  await advanceUntil(page, ownWork)
  await expect(ownWork, 'Alice is told why she cannot decide').toBeVisible()
  await expect(approval.getByRole('button', { name: 'Approve', exact: true }), 'Alice has no Approve button').toHaveCount(0)
  if (desktop) await expectEndsAboveTheFold(ownWork, "the approval panel's own-work line")
  await record(page, info, 'overview-pause')

  await advanceUntil(page, page.locator('li[data-gate="open"]'))
  await record(page, info, 'overview-writing')

  await advanceUntil(page, lineEnded(page, 'done'))
  await expect(headline(page)).toHaveText('MOCK-142 is in Jira')
  await expect(page.getByRole('region', { name: 'Written' }), 'the written panel names the ticket').toContainText('MOCK-142')
  await record(page, info, 'overview-success')

  await page.locator('#earlier-title').evaluate((heading) => heading.scrollIntoView({ block: 'start' }))
  await page.waitForTimeout(600)
  await record(page, info, 'overview-earlier-runs', { viewportOnly: true })
})

/** The height of a stop's words block beyond its name: the block's top padding, plus the caption row when the stop keeps one. */
async function roomBeyondName(page: Page, stop: string, name: string): Promise<number> {
  const label = page.locator(`li[data-stop="${stop}"]`).getByText(name, { exact: true })
  const [labelBox, blockBox] = await Promise.all([label.boundingBox(), label.locator('xpath=..').boundingBox()])
  if (!labelBox || !blockBox) throw new Error(`the ${stop} stop is not on screen`)
  return blockBox.height - labelBox.height
}

test('on the phone the Draft stop keeps no empty caption row, and the stops that can hold a caption keep theirs', async ({ page }, info) => {
  test.skip(isDesktop(info.project.name), 'the caption rows are reserved only below 760 px')
  await openFrozen(page, '/')
  const CAPTION_ROW_PX = 26
  expect(await roomBeyondName(page, 'draft', 'Draft ticket'), 'no gap under "Draft ticket" before its caption exists').toBeLessThan(CAPTION_ROW_PX)
  expect(await roomBeyondName(page, 'agent:read_releases', 'Read GitHub releases'), 'the agent stop keeps the row its words arrive in').toBeGreaterThanOrEqual(CAPTION_ROW_PX)
})

test('an Approver approves in place on the overview, and their decision replaces the recorded one', async ({ page }, info) => {
  await openFrozen(page, '/')
  await switchUser(page, 'Bob')
  const approval = page.getByRole('region', { name: 'Approval' })
  const approve = approval.getByRole('button', { name: 'Approve', exact: true })
  const decline = approval.getByRole('button', { name: 'Decline', exact: true })
  await advanceUntil(page, approve)
  await expect(headline(page)).toHaveText('Waiting for your approval')
  await expect(decline).toBeVisible()
  if (isDesktop(info.project.name)) await expectEndsAboveTheFold(decline, "the approval panel's buttons")
  await record(page, info, 'overview-pause-bob')

  await approve.click()
  await advanceUntil(page, lineEnded(page, 'done'))
  await expect(headline(page), "Bob's decision writes the next ticket, not the recorded MOCK-142").toHaveText('MOCK-143 is in Jira')
  await record(page, info, 'overview-approved-in-place')
})
