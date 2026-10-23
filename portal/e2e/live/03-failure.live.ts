import { expect } from '@playwright/test'
import { headline, tracker } from '../support/flows'
import { PLATFORM_RETRY_DELAY_MS, setMockGithubMode } from './support/stack'
import { test } from './support/test'
import { CATCH_UP_MS, expectCaughtUp, runExampleFromBuilder, shot } from './support/ui'

/**
 * Well inside the feed's 30 s idle recheck. The platform keeps the event stream open after run_failed
 * (platform_api/monitoring/http.py), so run_retried arrives on it whether or not Retry reconnects the feed.
 */
const LEAVES_BREAK_MS = 12_000

test.afterEach(async () => {
  await setMockGithubMode('ok')
})

test('a GitHub outage stops the run, the AI troubleshooter explains it, and a retry from the Tracker reaches the approval pause', async ({ page, backend }, info) => {
  await setMockGithubMode('unavailable')
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()

  const runId = await runExampleFromBuilder(page, info, 'failure')

  const failed = await backend.waitForState(runId, ['failed'])
  expect(failed.reason, 'the agent could not read GitHub').toBe('AgentError')
  expect(failed.retryable).toBe(true)

  const advice = page.getByRole('region', { name: 'AI troubleshooter advice' })
  await expect(advice, 'the AI troubleshooter opens under the break').toBeVisible({ timeout: CATCH_UP_MS })
  const troubleshoot = await backend.get<{ advice: { likely_cause: string; suggestion: string } }>('alice', `/api/v1/runs/${runId}/troubleshoot`)
  for (const words of [troubleshoot.advice.likely_cause, troubleshoot.advice.suggestion]) {
    await expect(advice.getByText(words, { exact: true }), 'the panel says what the backend advises').toBeVisible()
  }
  const retry = advice.getByRole('button', { name: 'Retry run' })
  await expect(retry).toBeVisible()
  expect((await backend.tickets()).filter((ticket) => ticket.run_id === runId), 'nothing was written').toEqual([])
  await shot(page, info, 'failure-04-run-failed-troubleshooter')

  await setMockGithubMode('ok')
  await page.waitForTimeout(PLATFORM_RETRY_DELAY_MS + 1_000)
  const retries: string[] = []
  page.on('request', (request) => {
    if (request.method() === 'POST' && request.url().endsWith(`/api/v1/runs/${runId}/retry`)) retries.push(request.url())
  })
  // Two presses in one task, before React can draw the first.
  await retry.evaluate((button: HTMLElement) => {
    button.click()
    button.click()
  })
  await expect(
    tracker(page).getByText('Attempt 2', { exact: true }),
    "the Tracker leaves the break within 12 s of Retry run, not at the feed's 30 s recheck",
  ).toBeVisible({ timeout: LEAVES_BREAK_MS })
  await backend.waitToLeave(runId, 'failed')

  await backend.waitForState(runId, ['awaiting_approval'])
  await expect(headline(page), 'the retried run reaches the approval pause').toHaveText('Waiting for an Approver', { timeout: CATCH_UP_MS })
  await expectCaughtUp(page)
  await expect(advice, 'the troubleshooter is gone once the run moves on').toHaveCount(0)
  expect(retries, 'two presses in one tick send one retry').toHaveLength(1)
  expect((await backend.tickets()).filter((ticket) => ticket.run_id === runId), 'nothing is written while the retried run waits').toEqual([])
  await shot(page, info, 'failure-05-retried-awaiting-approval')
})
