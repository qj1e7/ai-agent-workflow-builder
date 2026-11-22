import path from 'node:path'
import type { Locator, Page } from '@playwright/test'
import { expectAccessible } from '../support/axe'
import { assertClean, watchPage } from '../support/test'
import { askAndWait, tag } from './support/edit'
import { connectMockModel } from './support/settings'
import type { Backend } from './support/stack'
import { expect, test } from './support/test'
import { devContext, OUT, shot } from './support/ui'

/**
 * Explain this workflow (ADR 0051, section 6): the report as layout B in the side panel, on its own page and in the chat, with
 * In short reworded only where the guard lets it through. The mock model smooths code's wording, except for a workflow that reads
 * facebook/react, whose smoothing drops a negation and is refused.
 */

const SECTIONS = ['Step by step', 'What it reads, writes and posts', 'Flags', 'Who approves each write', 'Settings', 'Approval']
const DAILY_8 = { day: 'every_day', at: '08:00' }

interface Made {
  readonly id: string
  readonly name: string
}

/** A release check that reads one repository and creates Jira tickets in MOCK after a yes, as the Planner's version checker lays it out. */
async function releaseCheck(backend: Backend, name: string, repository: string): Promise<Made> {
  const agents = [{ card_id: 'crd_version_checker', values: { 'GitHub repository': repository, 'Jira project': 'MOCK' } }]
  const made = await backend.post<{ use_case_id: string }>('alice', '/api/v1/agent-use-cases', { name, instruction: `Check ${repository} for a new release and raise a ticket in MOCK.`, agents, schedule: DAILY_8, on: true }, undefined, [201])
  return { id: made.use_case_id, name }
}

const panel = (page: Page): Locator => page.locator('#side-panel')
const panelHeading = (page: Page): Locator => page.locator('#side-panel-h')

const inShort = (scope: Locator): Locator => scope.locator('[data-in-short]')

async function expectEverySection(scope: Locator): Promise<void> {
  for (const title of SECTIONS) await expect(scope.locator('summary', { hasText: title }), `${title} is a row`).toBeVisible()
}

test.describe('Explain this workflow', () => {
  let fastapi: Made
  let react: Made
  let versioned: Made

  test.beforeAll(async ({ backend, baseURL }) => {
    await connectMockModel(String(baseURL))
    fastapi = await releaseCheck(backend, `FastAPI release check ${tag()}`, 'fastapi/fastapi')
    react = await releaseCheck(backend, `React release check ${tag()}`, 'facebook/react')
    versioned = await releaseCheck(backend, `Versioned check ${tag()}`, 'fastapi/fastapi')
    const saved = await backend.saveWorkflowSchedule('alice', versioned.id, { day: 'monday', at: '09:00' })
    expect(saved.status, `alice moves ${versioned.name} to version 2: ${JSON.stringify(saved.body)}`).toBe(200)
  })

  test.afterAll(async ({ backend }) => {
    for (const made of [fastapi, react, versioned]) await backend.delete('alice', `/api/v1/use-cases/${made.id}`, [200, 404])
  })

  test('EXPLAIN-panel: the Explain button on a workflow row opens its report in the side panel, with In short and the six section rows, and More details goes to its page', async ({ browser }, info) => {
    const context = await devContext(browser, 'alice', { reducedMotion: true })
    const page = await context.newPage()
    const watch = watchPage(page)
    await page.goto('/')
    await askAndWait(page, 'Check my workflows')
    await page.getByRole('button', { name: 'See all workflows' }).last().click()
    const row = panel(page).locator(`li[data-workflow-id="${fastapi.id}"]`)
    await row.getByRole('button', { name: /^Explain/ }).click()

    await expect(panelHeading(page)).toHaveText('Explain')
    await expect(panel(page).getByRole('heading', { level: 3, name: fastapi.name })).toBeVisible()
    await expect(inShort(panel(page)), 'In short leads, in code’s words').toContainText('it reads GitHub “fastapi/fastapi” and Jira “MOCK”', { timeout: 20_000 })
    await expectEverySection(panel(page))
    await expect(panel(page).getByText('Reworded', { exact: true }), 'the panel never asks for the reworded line').toHaveCount(0)
    await expect(panel(page).locator('details[open]'), 'every row starts closed while nothing needs an answer').toHaveCount(0)
    await panel(page).locator('summary', { hasText: 'Step by step' }).click()
    await expect(panel(page).locator('details[open]').getByText('“Read release”')).toBeVisible()
    await expect(panel(page).getByRole('link', { name: 'More details' })).toHaveAttribute('href', `/workflows/${fastapi.id}/explain`)
    await expectAccessible(page, path.join(OUT, 'axe'), 'explain-panel')
    await shot(page, info, 'explain-panel')

    await panel(page).getByRole('button', { name: 'Workflows', exact: true }).click()
    await expect(panelHeading(page), 'Back goes to the list it came from').toHaveText('Workflows')
    assertClean(watch)
    await context.close()
  })

  test('EXPLAIN-page: the Explain link on the Workflows page opens the full page, and keyboard Enter opens a row', async ({ browser }, info) => {
    const context = await devContext(browser, 'alice', { reducedMotion: true })
    const page = await context.newPage()
    const watch = watchPage(page)
    await page.goto('/workflows')
    await page.locator(`li[data-workflow-id="${fastapi.id}"]`).getByRole('link', { name: /^Explain/ }).click()
    await expect(page).toHaveURL(new RegExp(`/workflows/${fastapi.id}/explain$`))
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(fastapi.name)
    await expect(page.getByRole('main')).toContainText('Explain')
    await expectEverySection(page.getByRole('main'))
    const flags = page.locator('summary', { hasText: 'Flags' })
    await flags.focus()
    await page.keyboard.press('Enter')
    await expect(page.getByText('Fixed for you', { exact: true })).toBeVisible()
    await shot(page, info, 'explain-page')
    assertClean(watch)
    await context.close()
  })

  test('EXPLAIN-version: Explain on a version under Versions says Explain, version N, and that today’s rules checked it again', async ({ browser }, info) => {
    const context = await devContext(browser, 'alice', { reducedMotion: true })
    const page = await context.newPage()
    const watch = watchPage(page)
    await page.goto(`/workflows/${versioned.id}`)
    await page.locator('summary', { hasText: 'Details' }).click()
    const versions = page.getByRole('list', { name: 'Versions, newest first' })
    await versions.getByRole('listitem').last().getByRole('link', { name: /^Explain/ }).click()
    await expect(page).toHaveURL(new RegExp(`/workflows/${versioned.id}/explain\\?version=1$`))
    await expect(page.getByRole('main')).toContainText('Explain, version 1')
    await expect(page.getByRole('main')).toContainText('Version 1. Checked again under today’s rules.')
    await expect(page.getByRole('main')).toContainText('Graded Safe when it was published')
    await shot(page, info, 'explain-version')
    assertClean(watch)
    await context.close()
  })

  test('EXPLAIN-roles: an Approver sees Explain on the row, on the workflow page and on each version, and it opens the same report', async ({ browser }) => {
    const context = await devContext(browser, 'bob')
    const page = await context.newPage()
    await page.goto('/workflows')
    await expect(page.locator(`li[data-workflow-id="${versioned.id}"]`).getByRole('link', { name: /^Explain/ })).toBeVisible()
    await page.goto(`/workflows/${versioned.id}`)
    await page.locator('summary', { hasText: 'Details' }).click()
    await expect(page.getByRole('main').getByRole('link', { name: /^Explain/ }), 'one per version, and one in Details').toHaveCount(3)
    await page.getByRole('main').getByRole('link', { name: /^Explain/, exact: false }).first().click()
    await expect(page.getByRole('main')).toContainText('Step by step')
    await context.close()
  })

  test('EXPLAIN-chat: “explain the FastAPI release check” shows the card with the Reworded pill, and Show code’s wording swaps to code’s In short', async ({ browser }, info) => {
    const context = await devContext(browser, 'alice', { reducedMotion: true })
    const page = await context.newPage()
    const watch = watchPage(page)
    await page.goto('/')
    const answer = await askAndWait(page, `explain the ${fastapi.name}`)
    await expect(answer.getByRole('heading', { level: 3, name: fastapi.name })).toBeVisible()
    await expect(answer.getByText('Reworded', { exact: true }), 'the mock model’s smoothing of the FastAPI check passes every check').toBeVisible({ timeout: 30_000 })
    await expectEverySection(answer)
    const reworded = (await inShort(answer).innerText()).trim()
    expect(reworded, 'the reworded line is not code’s own').not.toContain('It changes nothing else.')
    await shot(page, info, 'explain-chat-reworded')

    await answer.getByRole('button', { name: 'Show code’s wording' }).click()
    await expect(answer.getByText('Code’s wording', { exact: true })).toBeVisible()
    await expect(inShort(answer)).toContainText('It changes nothing else.')
    await expect(answer.getByRole('button', { name: 'Show the reworded one' })).toBeVisible()
    await expectEverySection(answer)
    await answer.getByRole('button', { name: 'Show the reworded one' }).click()
    await expect(inShort(answer)).toHaveText(reworded)

    await answer.getByRole('button', { name: 'Open the workflow' }).click()
    await expect(panelHeading(page)).toHaveText(fastapi.name)
    assertClean(watch)
    await context.close()
  })

  test('EXPLAIN-guard: a workflow that reads facebook/react shows code’s wording with no Reworded pill, because the guard refuses the smoothing that drops a negation', async ({ browser }, info) => {
    const context = await devContext(browser, 'alice', { reducedMotion: true })
    const page = await context.newPage()
    const watch = watchPage(page)
    await page.goto('/')
    const answer = await askAndWait(page, `explain the ${react.name}`)
    await expect(answer.getByRole('heading', { level: 3, name: react.name })).toBeVisible()
    await expectEverySection(answer)
    await expect(inShort(answer)).toContainText('GitHub “facebook/react”')
    await expect(inShort(answer)).toContainText('It changes nothing else.')
    await expect(answer.getByText('Reworded', { exact: true })).toHaveCount(0)
    await expect(answer.getByRole('button', { name: /wording|reworded/i })).toHaveCount(0)
    await shot(page, info, 'explain-chat-guard')
    assertClean(watch)
    await context.close()
  })

  test('EXPLAIN-which: words that match several workflows ask Which workflow?, a choice explains it, and words that match none say so', async ({ browser }) => {
    const context = await devContext(browser, 'alice', { reducedMotion: true })
    const page = await context.newPage()
    await page.goto('/')
    const which = await askAndWait(page, 'explain the release check')
    await expect(which.getByRole('heading', { level: 3, name: 'Which workflow?' })).toBeVisible()
    await which.getByRole('button', { name: react.name, exact: true }).click()
    const chosen = page.getByRole('list', { name: 'Conversation with the Planner' }).locator(':scope > li').last()
    await expect(chosen.getByRole('heading', { level: 3, name: react.name })).toBeVisible({ timeout: 30_000 })

    const none = await askAndWait(page, 'explain the Kubernetes check')
    await expect(none.getByRole('heading', { level: 3, name: 'I can’t find a workflow called that.' })).toBeVisible()
    await expect(none).toContainText('I looked for “Kubernetes check”.')
    await none.getByRole('button', { name: 'Check my workflows' }).click()
    await expect(panelHeading(page)).toHaveText('Workflows')
    await context.close()
  })

  test('EXPLAIN-it: “explain it” explains the workflow open in the side panel', async ({ browser }) => {
    const context = await devContext(browser, 'alice', { reducedMotion: true })
    const page = await context.newPage()
    await page.goto('/')
    await askAndWait(page, 'Check my workflows')
    await page.getByRole('button', { name: 'See all workflows' }).last().click()
    await panel(page).locator(`li[data-workflow-id="${react.id}"]`).getByRole('button', { name: new RegExp(`^${react.name}`) }).first().click()
    await expect(panelHeading(page)).toHaveText(react.name)
    const answer = await askAndWait(page, 'explain it')
    await expect(answer.getByRole('heading', { level: 3, name: react.name })).toBeVisible({ timeout: 30_000 })
    await context.close()
  })
})
