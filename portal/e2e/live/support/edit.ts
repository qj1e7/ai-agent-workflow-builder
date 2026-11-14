import { randomUUID } from 'node:crypto'
import type { Locator, Page } from '@playwright/test'
import type { Backend } from './stack'
import { expect } from './test'

const AGENTS = [{ card_id: 'crd_version_checker', values: { 'GitHub repository': 'langchain-ai/langgraph', 'Jira project': 'MOCK' } }]

export interface Made {
  readonly id: string
  readonly name: string
}

/** Letters only, so no part of a workflow's name is ever read as a day or a time. */
export const tag = (): string =>
  randomUUID()
    .replace(/[^a-f]/g, '')
    .padEnd(5, 'b')
    .slice(0, 5)

/** An agent workflow of alice's that runs on the schedule given, saved on its page, so it is at version 2. */
export async function scheduledWorkflow(backend: Backend, name: string, schedule: { day: string; at: string }): Promise<Made> {
  const made = await backend.post<{ use_case_id: string }>('alice', '/api/v1/agent-use-cases', { name, instruction: 'Check LangGraph for a new release and raise a ticket in MOCK.', agents: AGENTS }, undefined, [201])
  const saved = await backend.send('PUT', 'alice', `/api/v1/use-cases/${made.use_case_id}/schedule`, schedule)
  expect(saved.status, `alice sets ${name}’s schedule: ${JSON.stringify(saved.body)}`).toBe(200)
  return { id: made.use_case_id, name }
}

export interface Shown {
  readonly version: number
  readonly state: string
  readonly schedule: { day: string; at: string } | null
}

export const shown = (backend: Backend, id: string): Promise<Shown> => backend.get<Shown>('alice', `/api/v1/use-cases/${id}`)

export const versionsOf = async (backend: Backend, id: string) =>
  (await backend.get<{ versions: { version: number; by: string | null; via: string | null; undid: number | null }[] }>('alice', `/api/v1/use-cases/${id}/versions`)).versions

const said = (page: Page): Locator => page.getByRole('list', { name: 'Conversation with the Planner' }).locator(':scope > li')

/** The newest answer in the chat. */
export const newestAnswer = (page: Page): Locator => said(page).last()

/** The edit card in an answer. */
export const editCard = (answer: Locator): Locator => answer.locator('[data-card="edit"]')

/** Asks the Planner and waits for its answer to land. The answer is held by its place, so it stays this answer after later ones. */
export async function askAndWait(page: Page, text: string): Promise<Locator> {
  const box = page.getByLabel('Ask, or describe a task')
  const before = await said(page).count()
  await box.fill(text)
  await box.press('Enter')
  await expect(said(page)).toHaveCount(before + 2)
  const answer = said(page).nth(before + 1)
  await expect(answer).toHaveAttribute('data-answer', 'true', { timeout: 30_000 })
  return answer
}

/** The read of the workflow a save sets off. A change made elsewhere before it lands would show in the card at once, so a test waits for it first. */
export const rereadOf = (page: Page, id: string) => page.waitForResponse((answer) => answer.request().method() === 'GET' && new URL(answer.url()).pathname === `/api/v1/use-cases/${id}`)
