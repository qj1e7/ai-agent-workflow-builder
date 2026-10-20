import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: 'e2e',
  outputDir: 'e2e/out/results',
  reporter: [['list']],
  fullyParallel: true,
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
    { name: 'desktop', use: { viewport: { width: 1440, height: 900 } } },
    {
      name: 'phone',
      use: { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true },
    },
  ],
})
