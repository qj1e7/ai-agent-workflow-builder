import { test, expect } from './support/test'
import { shot } from './support/ui'

/** A DevNet host is plain HTTP and not localhost, so the browser calls it an insecure context. The compose name `portal` is one. */
const PLAIN_HTTP_URL = process.env['PLAIN_HTTP_URL'] ?? 'http://portal:8080'

test.use({ baseURL: PLAIN_HTTP_URL })

test('the Portal opens from a plain HTTP origin that is not localhost, and names the person from /me', async ({ page, backend }, info) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  expect(await page.evaluate(() => window.isSecureContext), `${PLAIN_HTTP_URL} is not a secure context`).toBe(false)
  expect(await page.evaluate(() => typeof crypto.randomUUID), 'the browser has no crypto.randomUUID here').toBe('undefined')

  const me = await backend.get<{ display: string }>('alice', '/api/v1/me')
  await expect(page.getByRole('banner'), 'the header names the person the platform knows').toContainText(me.display)
  await expect(page.getByRole('heading', { level: 1 })).toContainText(me.display)
  await shot(page, info, 'plain-http-04-home')
})
