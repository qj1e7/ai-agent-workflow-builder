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
 * Explain in the chat (ADR 0051, section 6): the Planner's answer to “explain the …” shows the report as layout B, with In short
 * reworded only where the guard lets it through. The mock model smooths code's wording, except for a workflow that reads
 * facebook/react, whose smoothing drops a negation and is refused. The Explain page is gone: no row, workflow page, version or
 * side panel links to it, and an old Explain address opens the workflow's page.
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

  test('EXPLAIN-gone: no Explain on a Workflows row, the workflow page, its versions or the side panel, and an old Explain address opens the workflow’s page', async ({ browser }, info) => {
    for (const person of ['alice', 'bob'] as const) {
      const context = await devContext(browser, person, { reducedMotion: true })
      const page = await context.newPage()
      const watch = watchPage(page)
      await page.goto('/workflows')
      const row = page.locator(`li[data-workflow-id="${versioned.id}"]`)
      await expect(row.getByRole('link', { name: new RegExp(`^${versioned.name}`) }), person).toBeVisible()
      await expect(row.getByRole('link', { name: /^Explain/ }), `${person}: no Explain on the row`).toHaveCount(0)

      await page.goto(`/workflows/${versioned.id}`)
      await page.locator('summary', { hasText: 'Details' }).click()
      await expect(page.getByRole('list', { name: 'Versions, newest first' }).getByRole('listitem'), 'both versions are listed').toHaveCount(2)
      await expect(page.getByRole('main').getByRole('link', { name: /^Explain/ }), `${person}: no Explain on the page or a version`).toHaveCount(0)
      await expect(page.getByRole('main').getByRole('button', { name: /^Explain/ })).toHaveCount(0)
      if (person === 'alice') await shot(page, info, 'explain-gone-workflow-page')

      await page.goto(`/workflows/${fastapi.id}/explain?version=1`)
      await expect(page, 'an old Explain address opens the workflow’s page').toHaveURL(new RegExp(`/workflows/${fastapi.id}$`))
      await expect(page.getByRole('heading', { level: 1 })).toHaveText(fastapi.name)
      await expect(page.getByRole('main')).not.toContainText('Step by step')
      assertClean(watch)
      await context.close()
    }

    const context = await devContext(browser, 'alice', { reducedMotion: true })
    const page = await context.newPage()
    await page.goto('/')
    await askAndWait(page, 'Check my workflows')
    await page.getByRole('button', { name: 'See all workflows' }).last().click()
    const listed = panel(page).locator(`li[data-workflow-id="${fastapi.id}"]`)
    await expect(listed).toBeVisible()
    await expect(listed.getByRole('button', { name: /^Explain/ }), 'no Explain beside a row in the panel').toHaveCount(0)
    await listed.getByRole('button', { name: new RegExp(`^${fastapi.name}`) }).first().click()
    await expect(panelHeading(page)).toHaveText(fastapi.name)
    await expect(panel(page).getByRole('link', { name: /^Explain/ }), 'no Explain in the workflow’s panel').toHaveCount(0)
    await expectAccessible(page, path.join(OUT, 'axe'), 'explain-gone-panel')
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
