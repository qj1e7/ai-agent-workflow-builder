import { expect, type Locator, type Page } from '@playwright/test'
import { MOCK_MODEL, MOCK_MODEL_URL, SettingsApi } from './settings'

export const FOLLOW_UP =
  'Every weekday at 3pm, find bug tickets in MOCK with no update for 10 days and create one follow-up ticket that lists them'
export const RELEASE = 'Tell me when LangGraph has a new release'
export const NO_SCHEDULE = 'Find bug tickets in MOCK with no update for 10 days and create one follow-up ticket that lists them'
export const TEAMS = 'Every Monday at 9am, post a summary of stale tickets in Teams'

/** The mock model answers the Planner, so New workflow can read a task. alice saves it and bob confirms its address. */
export async function connectMockModel(baseURL: string): Promise<void> {
  const settings = await SettingsApi.connect(baseURL)
  try {
    if ((await settings.model()).active?.base_url === MOCK_MODEL_URL) return
    const saved = await settings.send<{ status: string }>('alice', 'PUT', '/api/v1/settings/model', {
      style: 'anthropic',
      base_url: MOCK_MODEL_URL,
      model: MOCK_MODEL,
      api_key: 'p13-live-key-not-real',
    })
    expect(saved.status, `alice saves the mock model: ${JSON.stringify(saved.body)}`).toBe(200)
    await settings.confirmAddress('bob')
    expect((await settings.model()).active?.base_url, 'the mock model is active').toBe(MOCK_MODEL_URL)
  } finally {
    await settings.dispose()
  }
}

export const heading = (page: Page) => page.getByRole('heading', { level: 1 })
export const stepHeading = (step: number, name: string) => new RegExp(`^New workflow, step ${String(step)} of 4: ${name}$`)
export const nextButton = (page: Page) => page.getByRole('main').getByRole('button', { name: 'Next', exact: true })

/** Next stays pressable while it is off, as aria-disabled. Playwright will not click such a button, so this presses it from the keyboard. */
export async function pressNext(page: Page): Promise<void> {
  await nextButton(page).focus()
  await page.keyboard.press('Enter')
}
export const rowsList = (page: Page) => page.getByRole('list', { name: 'What I understood' })
export const rowOf = (page: Page, label: 'When' | 'Looks for' | 'Does' | 'Where it goes'): Locator =>
  rowsList(page).locator('li').filter({ has: page.locator(`span:text-is("${label}")`) })

/** Types the task and presses Plan it. Answers the milliseconds until step 2 showed what the Planner read. */
export async function planIt(page: Page, task: string): Promise<number> {
  await page.getByLabel('What should happen?').fill(task)
  const pressed = Date.now()
  await page.getByRole('button', { name: 'Plan it' }).click()
  await expect(heading(page)).toHaveText(stepHeading(2, 'Check what I understood'))
  await expect(page.getByRole('list', { name: 'What I understood' }).or(page.getByRole('link', { name: 'Open Software watchlist' }))).toBeVisible()
  return Date.now() - pressed
}

/** Changes one row in step 2 by typing, as an Operator fixes what the Planner read. */
export async function fixRow(page: Page, label: Parameters<typeof rowOf>[1], text: string): Promise<void> {
  const row = rowOf(page, label)
  await row.getByRole('button', { name: /^(Change|Fill in)$/ }).click()
  await row.getByRole('textbox').fill(text)
  await row.getByRole('button', { name: 'Save' }).click()
  await expect(row).toContainText(text)
}

/** From step 2 with every row clear: waits for the plan, then goes through When to Turn it on. */
export async function throughToReview(page: Page, name: string): Promise<void> {
  await expect(page.getByRole('region', { name: 'What the workflow will do' })).toContainText('Changes data, waits for a yes')
  await expect(nextButton(page)).not.toHaveAttribute('aria-disabled', 'true')
  await nextButton(page).click()
  await expect(heading(page)).toHaveText(stepHeading(3, 'When it runs'))
  await expect(page.getByLabel('How often')).toHaveValue('weekdays')
  await expect(page.getByLabel('Time')).toHaveValue('15:00')
  await nextButton(page).click()
  await expect(heading(page)).toHaveText(stepHeading(4, 'Turn it on'))
  await page.getByLabel('Name').fill(name)
}

export async function turnOn(page: Page): Promise<string> {
  await page.getByRole('button', { name: 'Turn it on' }).click()
  await expect(heading(page)).toHaveText('Your workflow is on')
  const id = /\/new\/done\/([^/?#]+)$/.exec(page.url())?.[1]
  expect(id, 'the done page names the workflow').toBeTruthy()
  return id ?? ''
}
