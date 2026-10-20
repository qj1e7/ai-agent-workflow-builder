import { expect, type Page } from '@playwright/test'

const FOLD_PX = 900
const LEGEND_LIMIT_PX = 884

/**
 * At 1440 by 900 the stage, caption, transport and legend fit without scrolling, and a heading named here is
 * either wholly above the fold or wholly below it, never cut by it. Call it on a freshly opened page.
 */
export async function expectFitsTheFold(page: Page, headingId?: string): Promise<void> {
  const legend = await page.getByRole('list', { name: 'How to read the room' }).boundingBox()
  expect(legend, 'the legend is on the page').not.toBeNull()
  if (!legend) return
  expect(legend.y + legend.height, 'the legend ends at or above 884 px').toBeLessThanOrEqual(LEGEND_LIMIT_PX)
  if (!headingId) return
  const heading = await page.locator(`#${headingId}`).boundingBox()
  expect(heading, `#${headingId} is on the page`).not.toBeNull()
  if (!heading) return
  const cut = heading.y < FOLD_PX && heading.y + heading.height > FOLD_PX
  expect(cut, `#${headingId} is cut by the fold (top ${Math.round(heading.y)}, bottom ${Math.round(heading.y + heading.height)})`).toBe(false)
}
