import { analyzeInPage, blockingViolations } from './support/axe'
import { collisionSampler } from './support/collisions'
import { pumpWhile, START } from './support/clock'
import { measureLayout, MIN_TARGET, MIN_TEXT } from './support/layout'
import { movingAnimations, MOVING } from './support/motion'
import { outOfVisualOrder } from './support/keyboard'
import { expect, test } from './support/test'

// These prove the instruments can fail: each one is pointed at a page built to break its rule.

test('the layout guard reports what it should and nothing else', async ({ page }) => {
  await page.setContent(`
    <body style="margin:0">
      <button id="small" style="width:30px;height:30px">Tiny</button>
      <button id="big" style="width:60px;height:60px">Big</button>
      <a href="#" style="display:inline-block;width:80px;height:20px">Short link</a>
      <p style="font-size:10px">Fine print</p>
      <p style="font-size:16px">Body text</p>
      <div style="width:3000px;height:1px"></div>
    </body>`)
  const report = await page.evaluate(measureLayout, { minTarget: MIN_TARGET, minText: MIN_TEXT })
  expect(report.undersizedTargets.map((target) => target.text).sort()).toEqual(['Short link', 'Tiny'])
  expect(report.smallText.map((text) => text.text)).toEqual(['Fine print'])
  expect(report.overflow, 'the wide block makes the page scroll sideways').toBeGreaterThan(0)
})

test('the moving-animation detector sees a running transform animation and ignores an opacity one', async ({ page }) => {
  await page.setContent(`
    <style>
      @keyframes slide { from { transform: translateX(0) } to { transform: translateX(200px) } }
      @keyframes fade { from { opacity: 0 } to { opacity: 1 } }
    </style>
    <div id="a" style="animation: slide 5s linear infinite">moves</div>
    <div id="b" style="animation: fade 5s linear infinite">fades</div>`)
  const moving = await page.evaluate(movingAnimations, MOVING)
  expect(moving.map((animation) => `${animation.name} on ${animation.target}`)).toEqual(['slide on div#a'])
})

test('the collision sampler flags a speech card over a label and stays quiet when they are apart', async ({ page }) => {
  await page.setContent(`
    <body style="margin:0">
      <div data-room-label style="position:absolute;left:100px;top:100px;width:100px;height:20px">Jira</div>
      <div id="speech" data-speech style="position:absolute;left:300px;top:100px;width:100px;height:40px">Hello</div>
    </body>`)
  const sampler = await collisionSampler(page)
  await page.waitForTimeout(400)
  const quiet = await sampler.stop()
  expect(quiet.samples).toBeGreaterThan(2)
  expect(quiet.collisions, 'no overlap while they are apart').toEqual([])

  const again = await collisionSampler(page)
  await page.locator('#speech').evaluate((el) => {
    el.style.left = '150px'
  })
  await page.waitForTimeout(400)
  const hit = await again.stop()
  expect(hit.collisions.length, 'the overlap is reported').toBeGreaterThan(0)
  expect(hit.collisions[0]?.overlap).toEqual({ width: 50, height: 20 })
})

test('the tab order check flags a jump back up the page', () => {
  const stop = (label: string, top: number, left: number) => ({ id: 0, label, top, bottom: top + 40, left, rest: { style: '', width: 0 }, focused: { style: '', width: 0 }, pixelsChange: null })
  const inOrder = [stop('a', 0, 0), stop('b', 0, 200), stop('c', 100, 0)]
  expect(outOfVisualOrder(inOrder)).toEqual([])
  const jumpsBack = [stop('a', 0, 0), stop('c', 100, 0), stop('b', 0, 200)]
  expect(outOfVisualOrder(jumpsBack)).toHaveLength(1)
})

test('the axe run names a button without a name and reports nothing on a labelled one, on a paused clock', async ({ page }) => {
  const document = (button: string) =>
    `<!doctype html><html lang="en"><head><title>Axe guard</title></head><body><main><h1>Axe guard</h1>${button}</main></body></html>`
  await page.clock.install({ time: START })
  await page.setContent(document('<button id="unnamed"></button>'))
  await page.clock.pauseAt(START + 3_000)

  const broken = await pumpWhile(page, analyzeInPage(page))
  expect(blockingViolations(broken)).toEqual(['button-name (critical): #unnamed'])
  const again = await pumpWhile(page, analyzeInPage(page))
  expect(blockingViolations(again), 'a second run on the same page finds the same thing').toEqual(blockingViolations(broken))

  await page.setContent(document('<button id="named">Save</button>'))
  const clean = await pumpWhile(page, analyzeInPage(page))
  expect(clean.violations.map((violation) => violation.id)).toEqual([])
  expect(clean.passes.length, 'the rules did run').toBeGreaterThan(0)
})
