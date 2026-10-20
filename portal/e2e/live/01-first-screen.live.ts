import { expect, test } from './support/test'
import { shot } from './support/ui'

test('a fresh stack opens on a first screen with no runs', async ({ page, backend }, info) => {
  test.skip((await backend.runs()).length > 0, 'the stack already has runs, so there is no empty first screen to see')

  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Open the builder' })).toBeVisible()
  await shot(page, info, '00-first-screen-empty')
})
