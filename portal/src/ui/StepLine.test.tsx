import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { STEP_STATE_WORDS, StepLine, type StepDraw } from './StepLine'

const STEPS: readonly StepDraw[] = [
  { key: 'a', icon: 'schedule', state: 'done' },
  { key: 'b', icon: 'read', state: 'done' },
  { key: 'c', icon: 'gate', state: 'wait' },
  { key: 'd', icon: 'write', state: 'todo' },
]

const draw = (props: Partial<Parameters<typeof StepLine>[0]> = {}) => renderToStaticMarkup(<StepLine steps={STEPS} label="Last run: waiting for approval" {...props} />)

const statesOf = (html: string) => [...html.matchAll(/data-state="(\w+)"/g)].map((match) => match[1])

function withReducedMotion(reduce: boolean): void {
  vi.stubGlobal('window', { matchMedia: (query: string) => ({ matches: reduce && query === '(prefers-reduced-motion: reduce)' }) })
}

afterEach(() => vi.unstubAllGlobals())

describe('the small step line', () => {
  it('is one picture with one name, so a screen reader reads the sentence and not four circles', () => {
    const html = draw()
    expect(html).toMatch(/^<span class="[^"]*" role="img" aria-label="Last run: waiting for approval">/)
    expect(html.match(/role="img"/g)).toHaveLength(1)
  })

  it('draws one circle per step, in order, each with its state', () => {
    expect(statesOf(draw())).toEqual(['done', 'done', 'wait', 'todo'])
  })

  it("draws a stopped step as stop and a step not reached as dashed, the sketch's two looks", () => {
    const html = draw({
      steps: [
        { key: 'a', icon: 'read', state: 'err' },
        { key: 'b', icon: 'write', state: 'skip' },
      ],
    })
    expect(statesOf(html)).toEqual(['err', 'skip'])
  })

  it("comes in the sketch's two sizes", () => {
    expect(draw()).not.toContain('data-size="sm"')
    expect(draw({ size: 'sm' })).toContain('data-size="sm"')
  })

  it('rings the waiting step while motion is allowed, and holds still under reduced motion', () => {
    withReducedMotion(false)
    expect(draw()).toContain('data-ring')
    withReducedMotion(true)
    expect(draw()).not.toContain('data-ring')
  })

  it('says each state in a word of its own, for the places that read the steps one by one', () => {
    expect(STEP_STATE_WORDS.wait).toBe('Waiting for approval: ')
    expect(STEP_STATE_WORDS.err).toBe('Stopped here: ')
  })
})
