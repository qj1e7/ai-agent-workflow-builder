import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { AgentFace, JOB_BADGE_MIN_SIZE, type FaceState } from './AgentFace'

const STATES: FaceState[] = ['idle', 'thinking', 'working', 'waiting', 'success', 'error', 'stopped']
const draw = (state: FaceState, id = 'version_checker', size = 54) => renderToStaticMarkup(<AgentFace id={id} state={state} size={size} />)
const circles = (html: string) => (html.match(/<circle\b/g) ?? []).length

describe('an Orb', () => {
  it.each(STATES)('says it is %s on the face itself, hidden from screen readers', (state) => {
    const html = draw(state)
    expect(html).toContain(`data-state="${state}"`)
    expect(html).toContain('aria-hidden="true"')
    expect(html).toContain('data-face="orb"')
  })

  it('does not react on its first draw, so a run that loads finished stays still', () => {
    for (const state of STATES) expect(draw(state)).not.toContain('data-react')
  })

  it('is drawn in its own colour, and unknown agents keep the colour their id always gets', () => {
    expect(draw('idle', 'version_checker')).toContain('stop-color="var(--checker)"')
    expect(draw('idle', 'troubleshooter')).toContain('stop-color="var(--trouble)"')
    expect(draw('idle', 'security_reviewer')).toContain('stop-color="var(--agent-2)"')
  })

  it('wears its job badge from 32 px up and none below', () => {
    expect(draw('idle', 'version_checker', JOB_BADGE_MIN_SIZE)).toContain('data-job="magnifier"')
    expect(draw('idle', 'troubleshooter', 56)).toContain('data-job="wrench"')
    expect(draw('idle', 'version_checker', JOB_BADGE_MIN_SIZE - 1)).not.toContain('data-job')
  })

  it('does not claim a job for an agent whose job it does not know', () => {
    expect(draw('idle', 'patch_planner', 56)).not.toContain('data-job')
  })

  it('wears a status badge only while waiting, after an error, or once it succeeds', () => {
    const plain = circles(draw('idle'))
    expect(circles(draw('waiting'))).toBe(plain + 2)
    expect(circles(draw('error'))).toBe(plain + 2)
    expect(circles(draw('success'))).toBe(plain + 2)
    expect(circles(draw('stopped'))).toBe(plain)
  })

  it('thinks with three dots outside its body, and only then', () => {
    expect(circles(draw('thinking'))).toBe(circles(draw('idle')) + 3)
    expect(circles(draw('working'))).toBe(circles(draw('idle')))
  })

  it('closes its eyes when stopped and looks up when waiting', () => {
    const eyeHeights = (state: FaceState) => [...draw(state).matchAll(/<rect [^>]*height="([\d.]+)"/g)].map((m) => m[1])
    expect(eyeHeights('stopped')).toEqual(['1.8', '1.8'])
    expect(eyeHeights('waiting')).toEqual(['5.5', '5.5'])
    expect(eyeHeights('idle')).toEqual(['6.5', '6.5'])
  })
})

describe('the Planner', () => {
  it.each(STATES)('is the Visor bot on every screen while %s', (state) => {
    const html = draw(state, 'planner', 40)
    expect(html).toContain('data-face="visor"')
    expect(html).not.toContain('data-face="orb"')
    expect(html).toContain('aria-hidden="true"')
  })

  it('shows the same bot as Home, with the visor and its ear lights', () => {
    const html = draw('idle', 'planner', 48)
    expect(html).toContain('radialGradient')
    expect(html).toContain('width="48"')
    expect(html).not.toContain('data-job')
  })

  it('keeps the status badge, so waiting, a problem and success still show', () => {
    const plain = circles(draw('idle', 'planner'))
    for (const state of ['waiting', 'error', 'success'] as const) expect(circles(draw(state, 'planner'))).toBe(plain + 2)
    expect(circles(draw('stopped', 'planner'))).toBe(plain)
  })
})
