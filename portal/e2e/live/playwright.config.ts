import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: '.',
  testMatch: process.env['E2E_AUTH'] === 'oidc' ? /\.oidc\.ts$/ : /\.live\.ts$/,
  outputDir: '../out/live/results',
  reporter: [['list']],
  fullyParallel: false,
  workers: 1,
  timeout: 180_000,
  expect: { timeout: 10_000 },
  forbidOnly: Boolean(process.env['CI']),
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
