import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { AgentFace, type FaceState } from './AgentFace'

const STATES: FaceState[] = ['idle', 'thinking', 'working', 'waiting', 'success', 'error', 'stopped']
const draw = (state: FaceState, id = 'version_checker') => renderToStaticMarkup(<AgentFace id={id} state={state} />)
const circles = (html: string) => (html.match(/<circle\b/g) ?? []).length

describe('an agent face', () => {
  it.each(STATES)('says it is %s on the face itself, hidden from screen readers', (state) => {
    const html = draw(state)
    expect(html).toContain(`data-state="${state}"`)
    expect(html).toContain('aria-hidden="true"')
  })

  it('does not react on its first draw, so a run that loads finished stays still', () => {
    for (const state of STATES) expect(draw(state)).not.toContain('data-react')
  })

  it('wears a badge only while waiting, after an error, or once it succeeds', () => {
    const plain = circles(draw('idle'))
    expect(circles(draw('waiting'))).toBe(plain + 2)
    expect(circles(draw('error'))).toBe(plain + 2)
    expect(circles(draw('success'))).toBe(plain + 2)
    expect(circles(draw('stopped'))).toBe(plain)
  })

  it('thinks with three dots, and types only when it has no tool to move', () => {
    expect(circles(draw('thinking'))).toBe(circles(draw('idle')) + 3)
    expect(draw('working', 'patch_planner').match(/<rect\b/g)).toHaveLength(5)
    expect(draw('working', 'version_checker').match(/<rect\b/g)).toHaveLength(2)
  })
})
