import { expect, type Page } from '@playwright/test'
import { PLATFORM_RETRY_DELAY_MS, setMockGithubMode } from './support/stack'
import { test } from './support/test'
import { runExampleFromBuilder, shot } from './support/ui'

const approvalLink = (page: Page) => page.locator('a[href*="/approvals/apr_"]').first()

test.afterEach(async () => {
  await setMockGithubMode('ok')
})

test('a GitHub outage stops the run, the AI troubleshooter explains it, and a retry after recovery reaches the approval pause', async ({ page, backend }, info) => {
  await setMockGithubMode('unavailable')
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()

  const runId = await runExampleFromBuilder(page, info, 'failure')

  const failed = await backend.waitForState(runId, ['failed'])
  expect(failed.reason, 'the agent could not read GitHub').toBe('AgentError')
  expect(failed.retryable).toBe(true)

  const troubleshooter = page.getByRole('heading', { name: 'AI troubleshooter' })
  await expect(troubleshooter, 'the AI troubleshooter panel shows').toBeVisible()
  const { advice } = await backend.get<{ advice: { explanation: string; likely_cause: string; suggestion: string } }>('alice', `/api/v1/runs/${runId}/troubleshoot`)
  for (const words of [advice.explanation, advice.likely_cause, advice.suggestion]) {
    await expect(page.getByText(words).first(), 'the panel says what the backend advises').toBeVisible()
  }
  const retry = page.getByRole('button', { name: 'Retry run' })
  await expect(retry).toBeEnabled()
  expect((await backend.tickets()).filter((ticket) => ticket.run_id === runId), 'nothing was written').toEqual([])
  await shot(page, info, 'failure-04-run-failed-troubleshooter')

  await setMockGithubMode('ok')
  await page.waitForTimeout(PLATFORM_RETRY_DELAY_MS + 1_000)
  await retry.click()
  await backend.waitToLeave(runId, 'failed')

  await backend.waitForState(runId, ['awaiting_approval'])
  await expect(approvalLink(page), 'the retried run reaches the approval pause').toBeVisible()
  await expect(troubleshooter, 'the troubleshooter is gone once the run moves on').toBeHidden()
  expect((await backend.tickets()).filter((ticket) => ticket.run_id === runId), 'nothing is written while the retried run waits').toEqual([])
  await shot(page, info, 'failure-05-retried-awaiting-approval')
})
