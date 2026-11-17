import path from 'node:path'
import { expectAccessible } from '../support/axe'
import { assertClean, watchPage } from '../support/test'
import { askAndWait } from './support/edit'
import { connectMockModel } from './support/settings'
import { expect, test } from './support/test'
import { devContext, OUT, shot } from './support/ui'

/**
 * A workflow drafted from words (ADR 0051, build step 6): an Operator asks in the chat, the drafter lays it out, she sends it, a
 * different Approver decides on its own page, and it becomes a Draft on Workflows. The person who asked can never decide it.
 */

const WORDS = 'Draft an n8n workflow that every Monday at 09:00 checks langchain-ai/langgraph for a new release and raises a ticket in MOCK'

test.describe('Drafted workflow', () => {
  let useCaseId: string | null = null

  test.beforeAll(async ({ baseURL }) => {
    await connectMockModel(String(baseURL))
  })

  test.afterAll(async ({ backend }) => {
    if (useCaseId !== null) await backend.delete('alice', `/api/v1/use-cases/${useCaseId}`, [200, 404])
  })

  test('DRAFTED-flow: Carol drafts it in the chat and sends it, Bob approves it on its page, and it is a Draft on Workflows', async ({ browser, backend }, info) => {
    const carolContext = await devContext(browser, 'carol', { reducedMotion: true })
    const carol = await carolContext.newPage()
    const watchCarol = watchPage(carol)
    await carol.goto('/')
    const answer = await askAndWait(carol, WORDS)

    const card = answer.locator('section', { hasText: 'Revision 1' })
    await expect(card.locator('[data-draft-pill]'), 'the drafter works, then it is a Draft').toHaveText('Draft', { timeout: 90_000 })
    await expect(card.locator('[data-in-short]')).toBeVisible()
    await expect(card.getByText('Start from the Portal'), 'the step line leaves the Portal start out').toHaveCount(0)
    const name = (await card.getByRole('heading', { level: 3 }).innerText()).trim()
    await expect(card.getByRole('button', { name: 'Send for approval' })).toBeVisible()
    await expect(card.getByRole('button', { name: 'Ask for a change' })).toBeVisible()
    await expectAccessible(carol, path.join(OUT, 'axe'), 'drafted-card')
    await shot(carol, info, 'drafted-card')

    await card.getByRole('button', { name: 'Send for approval' }).click()
    await expect(card.locator('[data-draft-pill]')).toHaveText('Waiting for a yes', { timeout: 20_000 })
    await expect(card).toContainText('Waiting for an Approver. You can’t approve your own draft.')
    await shot(carol, info, 'drafted-waiting')

    const messages = await backend.teamsMessages()
    const posted = messages.findLast((message) => message.link.startsWith('/setup-approvals/'))
    expect(posted, 'the set-up approval is posted in Teams with a link to its page').toBeDefined()
    const link = posted?.link ?? ''

    await carol.goto(link)
    await expect(carol.getByRole('heading', { level: 1 })).toHaveText(name)
    await expect(carol.getByText('You can’t approve it.'), 'the person who asked for it reads why, not a button').toBeVisible()
    await expect(carol.getByRole('button', { name: 'Approve' })).toHaveCount(0)
    await expect(carol.getByRole('button', { name: 'Decline' })).toHaveCount(0)
    await shot(carol, info, 'setup-approval-carol')

    const bobContext = await devContext(browser, 'bob', { reducedMotion: true })
    const bob = await bobContext.newPage()
    const watchBob = watchPage(bob)
    await bob.goto(link)
    await expect(bob.getByRole('heading', { level: 1 })).toHaveText(name)
    await expect(bob.getByText('Set-up approval, from Carol’s draft')).toBeVisible()
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

    await carol.goto('/')
    await carol.goto('/workflows')
    const row = carol.locator('li[data-workflow-id]', { hasText: name }).first()
    await expect(row.getByText('Draft', { exact: true }), 'Workflows lists it as a Draft').toBeVisible()
    await shot(carol, info, 'drafted-on-workflows')

    assertClean(watchCarol)
    assertClean(watchBob)
    await carolContext.close()
    await bobContext.close()
  })
})
