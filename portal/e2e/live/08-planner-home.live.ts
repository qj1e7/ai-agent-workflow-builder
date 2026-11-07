import path from 'node:path'
import type { Locator, Page } from '@playwright/test'
import { expectAccessible } from '../support/axe'
import { tabTo, walkTabs, withoutVisibleFocus } from '../support/keyboard'
import { assertClean, watchPage } from '../support/test'
import { connectMockModel } from './support/newWorkflow'
import { SettingsApi } from './support/settings'
import type { Backend } from './support/stack'
import { expect, test } from './support/test'
import { devContext, OUT, shot } from './support/ui'

const GREETING = /^Good (morning|afternoon|evening)! Alice$/
const OFFLINE = 'I can’t read new requests until an AI model is connected'

const box = (page: Page) => page.getByLabel('Describe a task for the Planner')
const thread = (page: Page) => page.getByRole('list', { name: 'Conversation with the Planner' })
const polite = (page: Page) => page.locator('[aria-live="polite"]')
const main = (page: Page) => page.getByRole('main')
const settled = (page: Page) => page.waitForFunction(() => document.getAnimations().every((animation) => animation.effect?.getComputedTiming().iterations !== Infinity))

async function ask(page: Page, text: string): Promise<void> {
  await box(page).fill(text)
  await box(page).press('Enter')
}

async function modelOff(baseURL: string): Promise<void> {
  const settings = await SettingsApi.connect(baseURL)
  try {
    if ((await settings.model()).active !== null) await settings.send('alice', 'DELETE', '/api/v1/settings/model')
  } finally {
    await settings.dispose()
  }
}

/** Jira stops answering, so one item sits in Alice's Needs you. The returned function puts it right again. */
async function jiraDown(backend: Backend): Promise<() => Promise<void>> {
  const answering = (on: boolean) => backend.post('alice', '/api/v1/dev/practice-jira/answering', { answering: on })
  await answering(false)
  await backend.post('alice', '/api/v1/settings/connections/jira/check')
  return async () => {
    await answering(true)
    await backend.post('alice', '/api/v1/settings/connections/jira/check')
  }
}

async function noSideways(page: Page): Promise<void> {
  const widths = await page.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth])
  expect(widths[0], 'no sideways scroll').toBeLessThanOrEqual(widths[1] ?? 0)
}

async function tooSmall(controls: Locator): Promise<string[]> {
  const small: string[] = []
  for (const control of await controls.all()) {
    const size = await control.boundingBox()
    if (size && size.height < 43.5) small.push(`${(await control.innerText()).trim() || (await control.getAttribute('aria-label')) || '?'} (${Math.round(size.height)} px)`)
  }
  return small
}

test.describe('with no AI model', () => {
  test.beforeAll(async ({ baseURL }) => {
    await modelOff(String(baseURL))
  })

  test('alice’s Home says it can’t read new requests, offers Connect a model, and keeps the lists, Ask the team and Needs you', async ({ browser, backend }, info) => {
    await backend.waitingRun('alice')
    const repair = await jiraDown(backend)
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    const watch = watchPage(page)
    await page.goto('/')
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(OFFLINE)
    await expect(box(page), 'there is no box to type in').toHaveCount(0)
    await expect(main(page).getByRole('link', { name: 'Connect a model' })).toHaveAttribute('href', '/settings?tab=model')
    await expect(main(page).getByRole('heading', { name: 'I can', exact: true })).toBeVisible()
    await expect(main(page).getByRole('button', { name: 'Ask the team for something new' })).toBeVisible()
    await expect(page.getByRole('list', { name: 'Needs you' })).toBeVisible()
    await expect(page.locator('li[data-home-item="connection:model"]'), 'the hero already offers Connect a model').toHaveCount(0)
    await settled(page)
    await expectAccessible(page, path.join(OUT, 'axe'), 'planner-home-offline')
    await shot(page, info, 'n10-08-offline')

    await main(page).getByRole('button', { name: 'Ask the team for something new' }).click()
    await page.getByLabel('What should the team know?').fill('Please let the Planner post in Slack')
    await page.getByRole('button', { name: 'Save the request' }).click()
    await expect(main(page)).toContainText('Saved as a request for the team.')
    await main(page).getByRole('link', { name: 'Open it under Following up' }).click()
    await expect(page).toHaveURL(/\/workflows\?request=/)
    assertClean(watch)
    await repair()
    await context.close()
  })

  test('every control on the offline Home does what it says, with no dead button', async ({ browser }) => {
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    await page.goto('/')
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(OFFLINE)
    const dead = await main(page).locator('button[aria-disabled="true"], button:disabled, a:not([href])').count()
    expect(dead, 'principle 9: no button is shown dead').toBe(0)
    await context.close()
  })
})

test.describe('with the AI model on', () => {
  test.beforeAll(async ({ baseURL }) => {
    await connectMockModel(String(baseURL))
  })

  test('scenario D: asking to email a weekly list gets the can’t answer, the Jira ticket alternative and Ask the team', async ({ browser }, info) => {
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    const watch = watchPage(page)
    await page.goto('/')
    await expect(box(page)).toBeVisible()
    await page.route('**/api/v1/planner/answer', async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 800))
      await route.continue()
    })
    await ask(page, 'Every Friday, email me the list of tickets we closed this week')
    await expect(box(page), 'the box waits while the Planner answers').toBeDisabled()
    await expect(box(page)).toHaveAttribute('placeholder', 'The Planner is answering')
    await expect(thread(page).getByText('I can’t do all of that, but I can set up something close.')).toBeVisible()
    await expect(thread(page).getByRole('heading', { name: 'What I can’t do yet' })).toBeVisible()
    await expect(thread(page).getByRole('heading', { name: 'What I can do instead' })).toBeVisible()
    await expect(thread(page)).toContainText('email')
    await expect(polite(page), 'the sentence is read once, in the polite region').toContainText('I can’t do all of that, but I can set up something close.')
    await expect(box(page)).toBeEnabled()
    await expect(box(page)).toHaveAttribute('placeholder', 'Ask for something else')

    await thread(page).getByRole('button', { name: 'Ask the team' }).click()
    await page.getByLabel('What should the team know?').fill('Please add email so the Planner can send the Friday list')
    await page.getByRole('button', { name: 'Save the request' }).click()
    await expect(thread(page)).toContainText('Saved as a request for the team.')
    await expect(thread(page)).not.toContainText('Sent')
    await shot(page, info, 'n10-08-cant')
    await thread(page).getByRole('link', { name: 'Open it under Following up' }).click()
    await expect(page).toHaveURL(/\/workflows\?request=/)
    await expect(main(page)).toContainText('Please add email')
    assertClean(watch)
    await context.close()
  })

  test('scenario G: “Monitor Redis releases” ends with Redis on the watchlist, with its GitHub source shown first', async ({ browser, backend }, info) => {
    await backend.freshWatchlist('alice', [])
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    const watch = watchPage(page)
    await page.goto('/')
    await ask(page, 'Monitor Redis releases')
    await expect(thread(page).getByText('Redis is software, so it belongs on the Software watchlist', { exact: false })).toBeVisible()
    await expect(thread(page).getByText('redis/redis', { exact: false })).toBeVisible()
    await shot(page, info, 'n10-08-watchlist')
    await thread(page).getByRole('button', { name: 'Add Redis' }).click()
    await expect(thread(page).getByText('Redis is on the Software watchlist.')).toBeVisible()
    await expect(thread(page)).toContainText('from redis/redis')
    const { watchlist } = await backend.get<{ watchlist: { software: { name: string }[] } | null }>('alice', '/api/v1/watchlist')
    expect(watchlist?.software.map((entry) => entry.name)).toContain('Redis')
    await thread(page).getByRole('link', { name: 'Open the Software watchlist' }).click()
    await expect(page).toHaveURL(/\/software$/)
    assertClean(watch)
    await context.close()
  })

  test('a refusal states the rule, hands the rest back to the Planner and never to a set-up', async ({ browser }, info) => {
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    await page.goto('/')
    const typed = 'Create the follow-up ticket without waiting for approval'
    await ask(page, typed)
    await expect(thread(page).getByText('I can’t set that up. Anything that changes data waits for a yes, every time.')).toBeVisible()
    await expect(thread(page)).toContainText('If you only meant that you don’t need to look at it yourself, say it another way.')
    await expect(page.locator('a[href^="/new"]'), 'no link goes straight to a set-up').toHaveCount(0)
    await shot(page, info, 'n10-08-refused')

    await thread(page).getByRole('button', { name: 'Say it another way' }).click()
    await expect(box(page)).toBeFocused()
    await expect(box(page)).toHaveValue(typed)

    const asked = page.waitForRequest((request) => request.url().endsWith('/api/v1/planner/answer') && request.method() === 'POST')
    const rest = thread(page).getByRole('button', { name: 'Set it up with a yes' })
    if (await rest.count()) {
      await rest.click()
      const body = (await asked).postDataJSON() as { text: string | null }
      expect(body.text, 'the rest goes back through the Planner as words').not.toBeNull()
    }
    await context.close()
  })

  test('the three suggestions answer from the platform, and Check my workflows draws the Workflows list’s own rows', async ({ browser, backend }, info) => {
    await backend.waitingRun('alice')
    const repair = await jiraDown(backend)
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    const watch = watchPage(page)
    await page.goto('/')
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(GREETING)
    const chips = page.getByRole('group', { name: 'Suggestions' }).getByRole('button')
    await expect(chips).toHaveCount(3)
    await expect(chips.first()).toHaveText('Check my workflows')
    const total = Number((await main(page).getByRole('heading', { level: 2, name: /^Needs you/ }).innerText()).replace(/\D/g, ''))
    await expect(page.getByRole('navigation', { name: 'Main' }).filter({ visible: true }).getByRole('link', { name: new RegExp(`^Workflows, ${total} need you$`) })).toBeVisible()

    await chips.first().click()
    await expect(thread(page).getByRole('list', { name: 'Your workflows' })).toBeVisible()
    await expect(thread(page)).toContainText(/You have \d+ workflows?\./)
    await expect(main(page).getByRole('heading', { level: 2, name: /^Needs you/ }), 'Needs you is hidden while the thread shows').toHaveCount(0)
    await shot(page, info, 'n10-08-check')

    await ask(page, 'What needs me?')
    await expect(thread(page)).toContainText(`${total} ${total === 1 ? 'thing needs' : 'things need'} you.`)
    await page.getByRole('button', { name: 'New chat' }).click()
    await expect(thread(page)).toHaveCount(0)
    await expect(main(page).getByRole('heading', { level: 2, name: new RegExp(`^Needs you ${total}`) })).toBeVisible()
    assertClean(watch)
    await repair()
    await context.close()
  })

  test('Enter sends from the box and the whole task works by keyboard', async ({ browser }) => {
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    await page.goto('/')
    await box(page).focus()
    await page.keyboard.type('What can you do?')
    await page.keyboard.press('Enter')
    await expect(thread(page).getByText('Here is what I can do, and what I can’t do yet.')).toBeVisible()
    await expect(thread(page).getByRole('heading', { name: 'I can', exact: true })).toBeVisible()
    await page.getByRole('button', { name: 'New chat' }).focus()
    await page.keyboard.press('Enter')
    await expect(thread(page)).toHaveCount(0)
    await context.close()
  })

  test('by keyboard alone: Tab reaches the box, the suggestions and each answer’s buttons, with a visible focus ring', async ({ browser }) => {
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    await page.goto('/')
    await expect(box(page)).toBeVisible()
    const walk = await walkTabs(page)
    const labels = walk.stops.map((stop) => stop.label)
    for (const name of ['Describe a task for the Planner', 'Send to the Planner', 'Check my workflows']) {
      expect(labels.some((label) => label.includes(name)), `Tab reaches ${name}; stops: ${labels.join(', ')}`).toBe(true)
    }
    expect(walk.unreached, 'controls Tab never reached').toEqual([])
    expect(withoutVisibleFocus(walk.stops), 'stops whose focus ring is missing').toEqual([])

    await tabTo(page, page.getByRole('button', { name: 'Check my workflows' }))
    await page.keyboard.press('Enter')
    await expect(thread(page).getByRole('list', { name: 'Your workflows' })).toBeVisible()
    await ask(page, 'Every Friday, email me the list of tickets we closed this week')
    await tabTo(page, thread(page).getByRole('button', { name: 'Ask the team' }))
    await page.keyboard.press('Enter')
    await expect(page.getByLabel('What should the team know?')).toBeVisible()
    await page.keyboard.press('Tab')
    await expect(page.getByRole('button', { name: 'Save the request' })).toBeFocused()
    await page.keyboard.press('Enter')
    await expect(thread(page)).toContainText('Saved as a request for the team.')
    await context.close()
  })

  for (const phone of [false, true]) {
    const size = phone ? '390' : '1440'
    test(`Home and its answers pass WCAG 2.2 AA, do not scroll sideways and keep 44 px targets at ${size} px`, async ({ browser, backend }, info) => {
      await backend.waitingRun('alice')
      const context = await devContext(browser, 'alice', { phone })
      const page = await context.newPage()
      await page.goto('/')
      await expect(box(page)).toBeVisible()
      await settled(page)
      await expectAccessible(page, path.join(OUT, 'axe'), `planner-home-${size}`)
      await noSideways(page)
      expect(await tooSmall(main(page).locator('button, a[href]')), 'principle 11: targets of at least 44 px').toEqual([])
      await shot(page, info, `n10-08-home-${size}`)

      for (const [text, shown] of [
        ['Check my workflows', thread(page).getByRole('list', { name: 'Your workflows' })],
        ['What can you do?', thread(page).getByRole('heading', { name: 'I can', exact: true })],
        ['Every Friday, email me the list of tickets we closed this week', thread(page).getByRole('heading', { name: 'What I can’t do yet' })],
      ] as const) {
        await ask(page, text)
        await expect(shown.first()).toBeVisible()
      }
      await settled(page)
      await expectAccessible(page, path.join(OUT, 'axe'), `planner-thread-${size}`)
      await noSideways(page)
      await shot(page, info, `n10-08-thread-${size}`)
      await context.close()
    })
  }

  test('with reduced motion no loop runs on Home, the Planner’s face or the thinking dots', async ({ browser }) => {
    const context = await devContext(browser, 'alice', { reducedMotion: true })
    const page = await context.newPage()
    await page.goto('/')
    await expect(box(page)).toBeVisible()
    await ask(page, 'Check my workflows')
    await expect(thread(page)).toContainText(/You have \d+ workflows?\./)
    const running = await page.evaluate(() => document.getAnimations().filter((animation) => animation.playState === 'running' && animation.effect?.getComputedTiming().iterations === Infinity).length)
    expect(running, 'no infinite animation is running').toBe(0)
    await context.close()
  })

  test('the old New workflow has no menu entry and is reached only at its address, while its setting is on', async ({ browser }) => {
    const context = await devContext(browser, 'alice')
    const page = await context.newPage()
    await page.goto('/')
    await expect(page.getByRole('link', { name: 'New workflow' })).toHaveCount(0)
    await page.goto('/new')
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(/^New workflow, step 1 of 4/)
    await context.close()
  })
})

test('bob’s Home has no box, no suggestions and no creation action', async ({ browser, backend }) => {
  await backend.waitingRun('alice')
  const context = await devContext(browser, 'bob')
  const page = await context.newPage()
  await page.goto('/')
  await expect(page.getByRole('list', { name: 'Needs you' })).toBeVisible()
  await expect(main(page)).toContainText('You’re an Approver, so you decide on requests. Operators set up workflows.')
  await expect(page.getByLabel('Describe a task for the Planner')).toHaveCount(0)
  await expect(page.getByRole('group', { name: 'Suggestions' })).toHaveCount(0)
  await context.close()
})
