import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'

const ROUTES = ['/', '/runs/run_01JB8', '/builder']
const ORIGIN = new URL(process.env['BASE_URL'] ?? 'http://localhost:8080').origin

async function openWithGuards(page: Page, path: string) {
  const cspViolations: string[] = []
  const foreignRequests: string[] = []
  page.on('console', (message) => {
    if (message.type() === 'error' && /Content Security Policy/i.test(message.text())) cspViolations.push(message.text())
  })
  page.on('request', (request) => {
    if (!request.url().startsWith('data:') && new URL(request.url()).origin !== ORIGIN) foreignRequests.push(request.url())
  })
  const response = await page.goto(path)
  await page.locator('#main').waitFor()
  return { response, cspViolations, foreignRequests }
}

for (const path of ROUTES) {
  test(`serves the app at ${path}`, async ({ page }) => {
    const { response, cspViolations, foreignRequests } = await openWithGuards(page, path)
    expect(response?.status()).toBe(200)
    await expect(page.locator('#main')).toBeVisible()
    expect(cspViolations).toEqual([])
    expect(foreignRequests).toEqual([])
  })
}

test('runs in demo mode and says so', async ({ page, request }) => {
  const config = await request.get('/config.json')
  expect(await config.json()).toEqual({ mode: 'demo' })
  await page.goto('/')
  await expect(page.getByText('Demo data').first()).toBeVisible()
})

test('sends the security headers', async ({ request }) => {
  const response = await request.get('/')
  const headers = response.headers()
  expect(headers['content-security-policy']).toContain("default-src 'self'")
  expect(headers['content-security-policy']).toContain("frame-ancestors 'none'")
  expect(headers['x-content-type-options']).toBe('nosniff')
  expect(headers['referrer-policy']).toBe('no-referrer')
  expect(headers['x-frame-options']).toBe('DENY')
  expect(headers['cross-origin-opener-policy']).toBe('same-origin')
  expect(headers['cross-origin-resource-policy']).toBe('same-origin')
  expect(headers['permissions-policy']).toContain('camera=()')
  expect(headers['server']).toBe('nginx')
})

test('loads the app font from the same origin', async ({ page }) => {
  const fontRequests: string[] = []
  page.on('response', (response) => {
    if (response.request().resourceType() === 'font') fontRequests.push(response.url())
  })
  await page.goto('/')
  await page.locator('#main').waitFor()
  await page.evaluate('document.fonts.load(\'16px "Instrument Sans"\')')
  expect(fontRequests.length).toBeGreaterThan(0)
  for (const url of fontRequests) expect(new URL(url).pathname).toMatch(/^\/assets\/.+\.woff2$/)
  expect(await page.evaluate('document.fonts.check(\'16px "Instrument Sans"\')')).toBe(true)
})

test('does not scroll sideways', async ({ page }) => {
  await page.goto('/')
  await page.locator('#main').waitFor()
  const overflow = await page.evaluate<number>('document.documentElement.scrollWidth - document.documentElement.clientWidth')
  expect(overflow).toBeLessThanOrEqual(0)
})

test('has no serious or critical accessibility violations on the first screen', async ({ page }) => {
  await page.goto('/')
  await page.locator('#main').waitFor()
  const { violations } = await new AxeBuilder({ page }).analyze()
  const blocking = violations.filter((violation) => violation.impact === 'serious' || violation.impact === 'critical')
  expect(blocking.map((violation) => `${violation.id}: ${violation.nodes.map((node) => node.target.join(' ')).join(', ')}`)).toEqual([])
})
