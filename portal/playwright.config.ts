import { defineConfig } from '@playwright/test'

const DESKTOP_ONLY = /(guards|video)\.spec\.ts/
const AFTER_EVERYTHING = /inventory\.spec\.ts/

export default defineConfig({
  testDir: 'e2e',
  outputDir: 'e2e/out/results',
  reporter: [['list']],
  fullyParallel: true,
  workers: 4,
  timeout: 90_000,
  expect: { timeout: 5_000 },
  forbidOnly: Boolean(process.env['CI']),
  use: {
    baseURL: process.env['BASE_URL'] ?? 'http://localhost:8080',
    timezoneId: 'Asia/Singapore',
    locale: 'en-SG',
    screenshot: 'off',
    video: 'off',
    trace: 'off',
  },
  projects: [
    { name: 'desktop', testIgnore: AFTER_EVERYTHING, use: { viewport: { width: 1440, height: 900 } } },
    {
      name: 'phone',
      testIgnore: [DESKTOP_ONLY, AFTER_EVERYTHING],
      use: { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true },
    },
    { name: 'inventory', testMatch: AFTER_EVERYTHING, dependencies: ['desktop', 'phone'] },
  ],
})
