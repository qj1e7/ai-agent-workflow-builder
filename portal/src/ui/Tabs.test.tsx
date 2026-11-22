import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { Tabs } from './Tabs'
import { buttonIn, elementsOf, press } from './testing'

const TABS = [
  { id: 'connections', label: 'Connections' },
  { id: 'people', label: 'People and permissions' },
] as const

describe('the tab bar', () => {
  it('is one named group, with the tab that is showing pressed', () => {
    const html = renderToStaticMarkup(<Tabs label="Settings sections" tabs={TABS} current="people" onPick={() => undefined} />)
    expect(html).toMatch(/^<div[^>]*role="group"[^>]*aria-label="Settings sections"/)
    expect([...html.matchAll(/<button[^>]*aria-pressed="(true|false)"[^>]*>([^<]+)<\/button>/g)].map((match) => [match[2], match[1]])).toEqual([
      ['Connections', 'false'],
      ['People and permissions', 'true'],
    ])
  })

  it('picks the tab that is pressed', () => {
    const picked: string[] = []
    const elements = elementsOf(<Tabs label="Show" tabs={TABS} current="connections" onPick={(id) => picked.push(id)} />, [Tabs])
    press(buttonIn(elements, 'People and permissions'))
    expect(picked).toEqual(['people'])
  })
})
