import path from 'node:path'
import { expectAccessible } from '../support/axe'
import { expect, test } from './support/test'
import { connectAndSave, everythingOnThePage, MOCK_MODEL, openSettings, personRow, roleBox, settingsTab, SettingsApi, signedInAs } from './support/settings'
import { OUT, shot } from './support/ui'

const ONLY_OPERATORS = 'Only Operators change settings.'

let api: SettingsApi

test.beforeAll(async () => {
  api = await SettingsApi.connect(process.env['BASE_URL'] ?? 'http://localhost:8080')
})

test.afterAll(async () => {
  await api.dispose()
})

test('Settings opens on the AI model, and People and roles lists everyone with their roles', async ({ page }, info) => {
  await openSettings(page)
  await expect(settingsTab(page, 'AI model')).toHaveAttribute('aria-pressed', 'true')
  await settingsTab(page, 'People and roles').click()
  await expect(page).toHaveURL(/\/settings\?tab=people$/)
  await expect(settingsTab(page, 'People and roles')).toBeFocused()
  for (const [email, name] of [
    ['alice@example.test', 'Alice'],
    ['bob@example.test', 'Bob'],
    ['carol@example.test', 'Carol'],
  ] as const) {
    await expect(personRow(page, email)).toContainText(name)
  }
  await expect(roleBox(page, 'Approver', 'Bob')).toBeChecked()
  await expect(roleBox(page, 'Operator', 'Bob')).not.toBeChecked()
  await shot(page, info, 'p10-01-people')
})

test('an Operator adds a person, asks for them as an Approver, and another Approver confirms it', async ({ browser }, info) => {
  const suffix = Date.now().toString(36)
  const email = `mei.${suffix}@example.test`
  const name = `Mei ${suffix}`
  const alice = await signedInAs(browser, 'alice')
  const page = await alice.newPage()
  try {
    await openSettings(page, 'people')
    await page.getByLabel('Work email').fill(email)
    await page.getByLabel('Name', { exact: true }).fill(name)
    await page.getByRole('button', { name: 'Add', exact: true }).click()
    await expect(page.locator('#people-notice')).toContainText(`Added ${name}.`)
    await expect(personRow(page, email)).toContainText('Hasn’t signed in yet')
    await roleBox(page, 'Approver', name).click()
    await expect(personRow(page, email)).toContainText('Approver: waiting for another Approver to confirm')
    await expect(personRow(page, email).getByRole('button')).toHaveCount(0)
    await shot(page, info, 'p10-02-asked')

    const bob = await signedInAs(browser, 'bob')
    const bobPage = await bob.newPage()
    await openSettings(bobPage, 'people')
    await personRow(bobPage, email).getByRole('button', { name: `Confirm ${name} as an Approver` }).click()
    await expect(bobPage.locator('#people-notice')).toContainText(`${name} is now an Approver.`)
    await expect(roleBox(bobPage, 'Approver', name)).toBeChecked()
    await shot(bobPage, info, 'p10-03-confirmed')
    await bob.close()
    expect((await api.person(email))?.approver).toBe(true)
  } finally {
    const added = await api.person(email)
    if (added) await api.send('alice', 'DELETE', `/api/v1/people/${added.id}`)
    await alice.close()
  }
})

test('an Approver who is not an Operator sees both tabs read-only', async ({ browser }, info) => {
  const bob = await signedInAs(browser, 'bob')
  const page = await bob.newPage()
  for (const tab of ['model', 'people'] as const) {
    await openSettings(page, tab)
    await expect(page.getByRole('main')).toContainText(ONLY_OPERATORS)
    await expect(page.getByRole('main').locator('form')).toHaveCount(0)
    const editable = await page.getByRole('main').locator('input:not([disabled]), select:not([disabled]), textarea:not([disabled])').count()
    expect(editable, `${tab}: fields bob could change`).toBe(0)
  }
  await shot(page, info, 'p10-04-read-only')
  await bob.close()
})

test('unticking an Approver when only two are left explains the rule and changes nothing', async ({ page }) => {
  const approvers = (await api.people()).filter((person) => person.approver).map((person) => person.id)
  test.skip(approvers.length !== 2, `needs exactly two Approvers, found ${approvers.join(', ')}`)
  await openSettings(page, 'people')
  await roleBox(page, 'Approver', 'Bob').click()
  await expect(personRow(page, 'bob@example.test')).toContainText('At least 2 people must be Approvers, so nobody has to approve their own work.')
  await expect(roleBox(page, 'Approver', 'Bob')).toBeChecked()
  await expect(roleBox(page, 'Approver', 'Bob')).toBeFocused()
})

test('an Operator connects the mock model, and only the key’s last two characters ever show', async ({ page }, info) => {
  const before = await api.model()
  const key = `live-${Date.now().toString(36)}-not-a-real-key-zq`
  try {
    await openSettings(page)
    await connectAndSave(page, { key })
    if (await page.locator('#model-waiting').isVisible()) await api.confirmAddress('bob')
    await page.reload()
    await expect(page.locator('#model-now')).toContainText(`API key ending zq`)
    await expect(page.locator('#model-now')).toContainText(MOCK_MODEL)
    expect(await everythingOnThePage(page)).not.toContain(key.slice(0, -2))
    await shot(page, info, 'p10-05-model')
  } finally {
    if (before.active === null) await api.send('alice', 'DELETE', '/api/v1/settings/model')
  }
})

for (const phone of [false, true]) {
  test(`WCAG 2.2 AA: no violations on either Settings tab at ${phone ? 'phone' : 'desktop'} width`, async ({ browser }) => {
    const alice = await signedInAs(browser, 'alice', { phone })
    const page = await alice.newPage()
    for (const tab of ['model', 'people'] as const) {
      await openSettings(page, tab)
      await expectAccessible(page, path.join(OUT, 'axe'), `settings-${tab}-${phone ? 'phone' : 'desktop'}`)
      const widths = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, client: document.documentElement.clientWidth }))
      expect(widths.scroll, `${tab}: no sideways scroll`).toBeLessThanOrEqual(widths.client)
    }
    await alice.close()
  })
}
