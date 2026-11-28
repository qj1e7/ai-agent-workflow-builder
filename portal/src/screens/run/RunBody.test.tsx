import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { RunBody } from './RunBody'
import type { Station } from './runModel'
import { stopPointer } from './stage'

const html = (below: boolean, view: 'main' | 'n8n' = 'main') =>
  renderToStaticMarkup(
    <RunBody view={view} stage={<i data-stage-here />} below={below ? <b data-card /> : null} side={<u data-side />} />,
  )

const outer = (markup: string) => /^<div class="([^"]*)"/.exec(markup)?.[1]
const stageColumn = (markup: string) => /<div class="([^"]*)"><i data-stage-here/.exec(markup)?.[1]

describe('the run page body keeps one shape, so the stage never jumps', () => {
  it('has the same grid and the same stage column with the card under the stage as without it', () => {
    expect(outer(html(true))).toBe(outer(html(false)))
    expect(stageColumn(html(true))).toBe(stageColumn(html(false)))
    expect(outer(html(true))).toMatch(/withStage/)
  })

  it('puts the card under the stage in the stage column, and the side column apart', () => {
    const markup = html(true)
    expect(markup.indexOf('data-stage-here')).toBeLessThan(markup.indexOf('data-card'))
    expect(markup.indexOf('data-card')).toBeLessThan(markup.indexOf('data-side'))
    expect(html(false)).not.toContain('data-card')
  })

  it('draws no stage in the n8n view', () => {
    expect(html(false, 'n8n')).not.toContain('data-stage-here')
  })
})

const station = (state: Station['state']): Station => ({ key: state + Math.random(), spot: { at: 'gate' }, label: 'x', icon: 'gate', agent: null, state, face: 'idle', under: null })

describe('what the notch points at', () => {
  it('is the stopped step on the main view, and nothing in the n8n view where no stage is drawn', () => {
    const line = [station('done'), station('err'), station('todo')]
    expect(stopPointer('main', line)).toBeCloseTo(0.5, 5)
    expect(stopPointer('n8n', line)).toBeNull()
  })
})
