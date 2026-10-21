import { test, expect } from './support/test'

test('the API never redirects a browser to its internal host name', async ({ playwright, baseURL }) => {
  const origin = new URL(baseURL!).origin
  const http = await playwright.request.newContext({ baseURL: origin })
  // FastAPI used to answer a trailing slash with a redirect to http://platform-api:8000/..., which a browser cannot reach.
  const response = await http.get('/api/v1/runs/', { headers: { 'X-Dev-User': 'alice' }, maxRedirects: 0 })
  expect(response.status()).toBe(404)
  expect(response.headers()['location'], 'no redirect is sent').toBeUndefined()
  await http.dispose()
})
