import path from 'node:path'
import { expectAccessible } from '../support/axe'
import { assertClean, watchPage } from '../support/test'
import { askAndWait } from './support/edit'
import { connectMockModel } from './support/settings'
import { expect, test } from './support/test'
import { devContext, OUT, shot } from './support/ui'

/**
 * A workflow drafted from words (ADR 0051, build steps 6 and 7): an Operator asks in the chat, the drafter lays it out, and the card
 * asks the settings it still needs one at a time. Its one-time check is one line on the card (ADR 0053, item 3): Turn on asks for it,
 * a different Approver finds it in Needs you and decides on its own page, and Turn on then tests it and turns it on. The person who
 * asked, changed it or answered its questions can never decide it.
 */

const CHECK = 'An Approver checks it once before it first runs.'

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

  test('DRAFTED-flow: Alice presses Turn on, Bob checks it once from Needs you, and her Turn on then tests it and turns it on', async ({ browser, backend }, info) => {
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
    await expect(card.getByText('Who approves “Make the ticket” on each run?'), 'the card asks what it still needs').toBeVisible()
    await expect(card.getByText(CHECK), 'the one-time check is one line on the card').toBeVisible()
    await expect(card.getByRole('button', { name: 'Turn on' }), 'Turn on stays off until nothing is needed').toHaveCount(0)
    await card.getByRole('button', { name: 'Any Approver on the team' }).click()
    await expect(card.getByText('Who approves “Make the ticket” on each run?')).toHaveCount(0)
    await expect(card.getByRole('button', { name: 'Turn on' })).toBeVisible()
    await expect(card.getByRole('button', { name: 'Send for approval' }), 'no separate path to send it').toHaveCount(0)
    await expect(card.getByRole('button', { name: 'Ask for a change' })).toBeVisible()
    await expectAccessible(alice, path.join(OUT, 'axe'), 'drafted-card')
    await shot(alice, info, 'drafted-card')

    const setUpPosts = async () => (await backend.teamsMessages()).filter((message) => message.link.startsWith('/setup-approvals/'))
    const postedBefore = new Set((await setUpPosts()).map((message) => message.id))
    const postedNow = async () => (await setUpPosts()).find((message) => !postedBefore.has(message.id))
    await card.getByRole('button', { name: 'Turn on' }).click()
    await expect(card.getByText('Waiting for an Approver to check it.'), 'Turn on asks for the check instead of turning it on').toBeVisible({ timeout: 20_000 })
    await expect(card.locator('[data-draft-pill]'), 'it stays a Draft').toHaveText('Draft')
    await expect(card.getByRole('button', { name: 'Turn on' })).toHaveCount(0)
    await shot(alice, info, 'drafted-waiting')

    // The platform posts the request in Teams as a job of its own, so it can land a moment after the card says it waits.
    await expect.poll(postedNow, { message: 'the set-up approval is posted in Teams with a link to its page', timeout: 30_000 }).toBeDefined()
    const link = (await postedNow())?.link ?? ''

    // A second tab, so the chat that holds her card stays as it is.
    const aliceTab = await aliceContext.newPage()
    const watchAliceTab = watchPage(aliceTab)
    await aliceTab.goto(link)
    await expect(aliceTab.getByRole('heading', { level: 1 })).toHaveText(name)
    await expect(aliceTab.getByText("You can't approve it. You asked for it, changed it, answered its questions or sent it."), 'the person who asked for it reads why, not a button, though she is an Approver').toBeVisible()
    // Exact names: the rail's person button, "Alice, Operator and Approver", holds the word too.
    await expect(aliceTab.getByRole('button', { name: 'Approve', exact: true })).toHaveCount(0)
    await expect(aliceTab.getByRole('button', { name: 'Decline', exact: true })).toHaveCount(0)
    await shot(aliceTab, info, 'setup-approval-alice')
    await aliceTab.goto('/')
    await expect(aliceTab.locator(`a[href="${link}"]`), 'it is not in the Needs you of the person who made it').toHaveCount(0)

    const bobContext = await devContext(browser, 'bob', { reducedMotion: true })
    const bob = await bobContext.newPage()
    const watchBob = watchPage(bob)
    await bob.goto('/')
    const row = bob.locator(`a[href="${link}"]`)
    await expect(row, 'one Needs you row for an Approver who can say yes').toHaveCount(1)
    await expect(row).toContainText(`Alice asks for a one-time check of ${name}`)
    await shot(bob, info, 'setup-needs-you-bob')
    await row.click()
    await expect(bob).toHaveURL(new RegExp(`${link}$`))
    await expect(bob.getByRole('heading', { level: 1 })).toHaveText(name)
    await expect(bob.getByText('Set-up approval, from Alice’s draft')).toBeVisible()
    await expect(bob.locator('[data-draft-pill]')).toHaveText('Needs your approval')
    await expect(bob.getByRole('heading', { name: 'What it reads, writes and posts' })).toBeVisible()
    for (const heading of ['Who approves each write', 'Settings', 'Safety checks']) await expect(bob.getByRole('main').getByRole('heading', { name: heading, exact: true }), `${heading} is in view`).toBeVisible()
    await expect(bob.getByRole('main').getByText('Passed', { exact: true })).toBeVisible()
    await expect(bob.getByRole('main').getByRole('button', { name: 'More details' })).toHaveCount(0)
    await expectAccessible(bob, path.join(OUT, 'axe'), 'setup-approval-bob')
    await shot(bob, info, 'setup-approval-bob')
    await bob.getByRole('button', { name: 'Approve', exact: true }).click()
    await expect(bob.getByText('Approved by Bob.')).toBeVisible({ timeout: 20_000 })
    await expect(bob.getByText('Set up as a draft.')).toBeVisible({ timeout: 60_000 })
    const open = bob.getByRole('link', { name: 'Open it' })
    const href = await open.getAttribute('href')
    useCaseId = href?.split('/').at(-1) ?? null
    await shot(bob, info, 'setup-approval-approved')

    await expect(card.getByText('Bob checked it once.'), 'the same card says who checked it').toBeVisible({ timeout: 30_000 })
    await expect(card.getByText('Press Turn on. I do a test run, which writes nothing, and turn it on if the test passes.')).toBeVisible()
    await shot(alice, info, 'drafted-checked')
    await card.getByRole('button', { name: 'Turn on' }).click()
    await expect(answer.locator('[data-draft-pill]').last(), 'Turn on now tests it, which writes nothing, and turns it on').toHaveText('On', { timeout: 90_000 })
    await shot(alice, info, 'drafted-on')

    await alice.goto('/workflows')
    const listed = alice.locator(`li[data-workflow-id="${useCaseId ?? ''}"]`)
    await expect(listed.getByText('On', { exact: true }), 'Workflows lists it as On, as the card says').toBeVisible()
    await shot(alice, info, 'drafted-on-workflows')

    assertClean(watchAlice)
    assertClean(watchAliceTab)
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
    await expect(card.getByRole('button', { name: 'Turn on' })).toHaveCount(0)
    await shot(alice, info, 'drafted-question-time')

    await card.getByRole('button', { name: 'Type a time' }).click()
    await card.getByRole('textbox', { name: 'Type a time' }).fill('9')
    await card.getByRole('button', { name: 'Set' }).click()
    await expect(card.getByRole('alert'), 'a time it cannot read stays a question, with the words under the box').toContainText("I couldn't read a time in that.")
    await expect(card.getByText('Mondays, at what time?')).toBeVisible()

    await card.getByRole('textbox', { name: 'Type a time' }).fill('9:30')
    await card.getByRole('button', { name: 'Set' }).click()
    await expect(card.getByText('Mondays, at what time?')).toHaveCount(0)
    await expect(card.getByText('Who approves “Make the ticket” on each run?'), 'the next question comes up').toBeVisible()
    await card.getByRole('button', { name: 'Any Approver on the team' }).click()
    await expect(card.getByRole('button', { name: 'Turn on' })).toBeVisible()
    await expectAccessible(alice, path.join(OUT, 'axe'), 'drafted-card-answered')
    await shot(alice, info, 'drafted-question-answered')

    assertClean(watchAlice)
    await aliceContext.close()
  })
})
