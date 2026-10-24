import { defineConfig } from '@playwright/test'

const DESKTOP_ONLY = /(guards|video)\.spec\.ts/
const AFTER_EVERYTHING = /inventory\.spec\.ts/
/** Plays the run on the real clock under a trace, so it runs after the rest: it neither slows them nor is slowed by them. */
const STEADY = /steady\.spec\.ts/
/** The specs that record states. The dark projects run only these, so every state has a shot and an axe result in both themes. */
const RECORDING = /\/(overview|run|builder|approvals|inboxes|settings|software|reduced-motion)\.spec\.ts$/

const DESKTOP = { viewport: { width: 1440, height: 900 } }
const PHONE = { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true }

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
    { name: 'desktop', testIgnore: [AFTER_EVERYTHING, STEADY], use: DESKTOP },
    { name: 'phone', testIgnore: [DESKTOP_ONLY, AFTER_EVERYTHING, STEADY], use: PHONE },
    { name: 'desktop-dark', testMatch: RECORDING, use: { ...DESKTOP, colorScheme: 'dark' } },
    { name: 'phone-dark', testMatch: RECORDING, use: { ...PHONE, colorScheme: 'dark' } },
    { name: 'steady-desktop', testMatch: STEADY, dependencies: ['desktop', 'phone', 'desktop-dark', 'phone-dark'], use: DESKTOP },
    { name: 'steady-phone', testMatch: STEADY, dependencies: ['desktop', 'phone', 'desktop-dark', 'phone-dark'], use: PHONE },
    { name: 'inventory', testMatch: AFTER_EVERYTHING, dependencies: ['desktop', 'phone', 'desktop-dark', 'phone-dark'] },
  ],
})
