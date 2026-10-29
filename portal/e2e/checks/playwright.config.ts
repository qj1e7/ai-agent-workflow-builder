import { defineConfig } from '@playwright/test'

// The checker's P1 checks. scripts/checks/p1.sh runs them in the browser runner image, inside a stack's Portal container,
// so the page is at http://localhost:8080 (a secure context) and compose names such as platform-api resolve.
const EVID = process.env['EVID'] ?? '/tmp/swarm-p1'

export default defineConfig({
  testDir: '.',
  testMatch: /\.check\.ts$/,
  outputDir: `${EVID}/.playwright-results`,
  reporter: [['list']],
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 300_000,
  expect: { timeout: 15_000 },
  use: {
    baseURL: process.env['BASE_URL'] ?? 'http://localhost:8080',
    timezoneId: 'Asia/Singapore',
    locale: 'en-SG',
    viewport: { width: 1440, height: 900 },
    screenshot: 'off',
    video: 'off',
    trace: 'off',
  },
})
