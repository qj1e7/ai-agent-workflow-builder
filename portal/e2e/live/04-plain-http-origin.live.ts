import { test, expect } from './support/test'
import { runExampleFromBuilder, shot } from './support/ui'

/** A DevNet host is plain HTTP and not localhost, so the browser calls it an insecure context. The compose name `portal` is one. */
const PLAIN_HTTP_URL = process.env['PLAIN_HTTP_URL'] ?? 'http://portal:8080'

test.use({ baseURL: PLAIN_HTTP_URL })

test('run now works from a plain HTTP origin that is not localhost', async ({ page, backend }, info) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  expect(await page.evaluate(() => window.isSecureContext), `${PLAIN_HTTP_URL} is not a secure context`).toBe(false)
  expect(await page.evaluate(() => typeof crypto.randomUUID), 'the browser has no crypto.randomUUID here').toBe('undefined')

  const runId = await runExampleFromBuilder(page, info, backend, 'plain-http')
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  await shot(page, info, 'plain-http-04-run-page')

  const run = await backend.run(runId)
  expect(run.started_by, 'the platform started the run for the Operator').toBe('alice')
})
