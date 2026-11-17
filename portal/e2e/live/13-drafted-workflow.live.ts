import path from 'node:path'
import { expectAccessible } from '../support/axe'
import { assertClean, watchPage } from '../support/test'
import { askAndWait } from './support/edit'
import { connectMockModel } from './support/settings'
import { expect, test } from './support/test'
import { devContext, OUT, shot } from './support/ui'

/**
 * A workflow drafted from words (ADR 0051, build steps 6 and 7): an Operator asks in the chat, the drafter lays it out, the card asks
 * the settings it still needs one at a time, she sends it, a different Approver decides on its own page, and it becomes a Draft on
 * Workflows. The person who asked, changed it or answered its questions can never decide it.
 */

const WORDS = 'Draft an n8n workflow that every Monday at 09:00 checks langchain-ai/langgraph for a new release and raises a ticket in MOCK'
/** Names no time, so the card asks for one. */
const WORDS_NO_TIME = 'Draft an n8n workflow that every Monday checks langchain-ai/langgraph for a new release and raises a ticket in MOCK, for the questions'

test.describe('Drafted workflow', () => {
  let useCaseId: string | null = null

  test.beforeAll(async ({ baseURL }) => {
    await connectMockModel(String(baseURL))
  })

  test.afterAll(async ({ backend }) => {
    if (useCaseId !== null) await backend.delete('alice', `/api/v1/use-cases/${useCaseId}`, [200, 404])
  })

  test('DRAFTED-flow: Alice drafts it in the chat and sends it, Bob approves it on its page, and it is a Draft on Workflows', async ({ browser, backend }, info) => {
    const aliceContext = await devContext(browser, 'alice', { reducedMotion: true })
    const alice = await aliceContext.newPage()
    const watchAlice = watchPage(alice)
    await alice.goto('/')
    const answer = await askAndWait(alice, WORDS)

    // An answer makes a new revision that stays on this card, so the card is found by its pill and not by its revision.
    const card = answer.locator('section', { has: alice.locator('[data-draft-pill]') })
    await expect(card.locator('[data-draft-pill]'), 'the drafter works, then it is a Draft').toHaveText('Draft', { timeout: 90_000 })
    await expect(card.locator('[data-in-short]')).toBeVisible()
    await expect(card.getByText('Start from the Portal'), 'the step line leaves the Portal start out').toHaveCount(0)
    const name = (await card.getByRole('heading', { level: 3 }).innerText()).trim()
    await expect(card.getByText('Who says yes to “Make the ticket” on each run?'), 'the card asks what it still needs').toBeVisible()
    await expect(card.getByRole('button', { name: 'Send for approval' }), 'Send for approval stays off until nothing is needed').toHaveCount(0)
    await card.getByRole('button', { name: 'Any Approver on the team' }).click()
    await expect(card.getByText('Who says yes to “Make the ticket” on each run?')).toHaveCount(0)
    await expect(card.getByRole('button', { name: 'Send for approval' })).toBeVisible()
    await expect(card.getByRole('button', { name: 'Ask for a change' })).toBeVisible()
    await expectAccessible(alice, path.join(OUT, 'axe'), 'drafted-card')
    await shot(alice, info, 'drafted-card')

    await card.getByRole('button', { name: 'Send for approval' }).click()
    await expect(card.locator('[data-draft-pill]')).toHaveText('Waiting for a yes', { timeout: 20_000 })
    await expect(card).toContainText('Waiting for an Approver. You can’t approve your own draft.')
    await shot(alice, info, 'drafted-waiting')

    const messages = await backend.teamsMessages()
    const posted = messages.findLast((message) => message.link.startsWith('/setup-approvals/'))
    expect(posted, 'the set-up approval is posted in Teams with a link to its page').toBeDefined()
    const link = posted?.link ?? ''

    await alice.goto(link)
    await expect(alice.getByRole('heading', { level: 1 })).toHaveText(name)
    await expect(alice.getByText("You can't approve it. You asked for it, changed it, answered its questions or sent it."), 'the person who asked for it reads why, not a button, though she is an Approver').toBeVisible()
    await expect(alice.getByRole('button', { name: 'Approve' })).toHaveCount(0)
    await expect(alice.getByRole('button', { name: 'Decline' })).toHaveCount(0)
    await shot(alice, info, 'setup-approval-alice')

    const bobContext = await devContext(browser, 'bob', { reducedMotion: true })
    const bob = await bobContext.newPage()
    const watchBob = watchPage(bob)
    await bob.goto(link)
    await expect(bob.getByRole('heading', { level: 1 })).toHaveText(name)
    await expect(bob.getByText('Set-up approval, from Alice’s draft')).toBeVisible()
    await expect(bob.locator('[data-draft-pill]')).toHaveText('Needs your yes')
    await expect(bob.getByRole('heading', { name: 'What it reads, writes and posts' })).toBeVisible()
    await expectAccessible(bob, path.join(OUT, 'axe'), 'setup-approval-bob')
    await shot(bob, info, 'setup-approval-bob')
    await bob.getByRole('button', { name: 'Approve' }).click()
    await expect(bob.getByText('Approved by Bob.')).toBeVisible({ timeout: 20_000 })
    await expect(bob.getByText('Set up as a draft.')).toBeVisible({ timeout: 60_000 })
    const open = bob.getByRole('link', { name: 'Open it' })
    const href = await open.getAttribute('href')
    useCaseId = href?.split('/').at(-1) ?? null
    await shot(bob, info, 'setup-approval-approved')

    await alice.goto('/')
    await alice.goto('/workflows')
    const row = alice.locator('li[data-workflow-id]', { hasText: name }).first()
    await expect(row.getByText('Draft', { exact: true }), 'Workflows lists it as a Draft').toBeVisible()
    await shot(alice, info, 'drafted-on-workflows')

    assertClean(watchAlice)
    assertClean(watchBob)
    await aliceContext.close()
    await bobContext.close()
  })

  test('DRAFTED-questions: a time the card cannot read stays a question, a time it can read goes on to the next one', async ({ browser }, info) => {
    const aliceContext = await devContext(browser, 'alice', { reducedMotion: true })
    const alice = await aliceContext.newPage()
    const watchAlice = watchPage(alice)
    await alice.goto('/')
    const answer = await askAndWait(alice, WORDS_NO_TIME)

    const card = answer.locator('section', { has: alice.locator('[data-draft-pill]') })
    await expect(card.locator('[data-draft-pill]')).toHaveText('Draft', { timeout: 90_000 })
    await expect(card.getByText('Mondays, at what time?'), 'the words name no time, so it asks for one first').toBeVisible()
    await expect(card.getByRole('button', { name: 'Send for approval' })).toHaveCount(0)
    await shot(alice, info, 'drafted-question-time')

    await card.getByRole('button', { name: 'Type a time' }).click()
    await card.getByRole('textbox', { name: 'Type a time' }).fill('9')
    await card.getByRole('button', { name: 'Set' }).click()
    await expect(card.getByRole('alert'), 'a time it cannot read stays a question, with the words under the box').toContainText("I couldn't read a time in that.")
    await expect(card.getByText('Mondays, at what time?')).toBeVisible()

    await card.getByRole('textbox', { name: 'Type a time' }).fill('9:30')
    await card.getByRole('button', { name: 'Set' }).click()
    await expect(card.getByText('Mondays, at what time?')).toHaveCount(0)
    await expect(card.getByText('Who says yes to “Make the ticket” on each run?'), 'the next question comes up').toBeVisible()
    await card.getByRole('button', { name: 'Any Approver on the team' }).click()
    await expect(card.getByRole('button', { name: 'Send for approval' })).toBeVisible()
    await expectAccessible(alice, path.join(OUT, 'axe'), 'drafted-card-answered')
    await shot(alice, info, 'drafted-question-answered')

    assertClean(watchAlice)
    await aliceContext.close()
  })
})
