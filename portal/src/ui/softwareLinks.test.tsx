import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import { Link } from './Link'
import { SoftwareLinks, softwareLinkTarget } from './softwareLinks'

describe('softwareLinkTarget', () => {
  it('leads a software link to the watchlist workflow page, with the software it names', () => {
    expect(softwareLinkTarget('/software/sw_1', 'uc_wl')).toBe('/workflows/uc_wl?software=sw_1')
    expect(softwareLinkTarget('/software/a%20b', 'uc_wl')).toBe('/workflows/uc_wl?software=a+b')
    expect(softwareLinkTarget('/software', 'uc_wl')).toBe('/workflows/uc_wl')
  })

  it('leads to Workflows, where the old address lands, when there is no watchlist', () => {
    expect(softwareLinkTarget('/software/sw_1', null)).toBe('/workflows')
    expect(softwareLinkTarget('/software', null)).toBe('/workflows')
  })

  it('leaves an address with a bad percent sign as it is, instead of throwing', () => {
    expect(softwareLinkTarget('/software/100%', 'uc_wl')).toBe('/software/100%')
  })

  it('leaves every other address, and an address before the watchlist is known, as it is', () => {
    expect(softwareLinkTarget('/workflows/uc_1', 'uc_wl')).toBe('/workflows/uc_1')
    expect(softwareLinkTarget('/softwares', 'uc_wl')).toBe('/softwares')
    expect(softwareLinkTarget('/software/sw_1', undefined)).toBe('/software/sw_1')
  })
})

describe('a link to software', () => {
  const draw = (watchlist: string | null | undefined) =>
    renderToStaticMarkup(
      <MemoryRouter>
        <SoftwareLinks.Provider value={watchlist}>
          <Link to="/software/sw_1">Open</Link>
        </SoftwareLinks.Provider>
      </MemoryRouter>,
    )

  it('goes to its page, not through the old address', () => {
    expect(draw('uc_wl')).toContain('href="/workflows/uc_wl?software=sw_1"')
    expect(draw(null)).toContain('href="/workflows"')
    expect(draw(undefined)).toContain('href="/software/sw_1"')
  })
})
