import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { STEP_STATE_WORDS, StepLine, type StepDraw } from './StepLine'

const STEPS: readonly StepDraw[] = [
  { key: 'a', name: 'Check releases', icon: 'schedule', state: 'done' },
  { key: 'b', name: 'Compare', icon: 'read', state: 'done' },
  { key: 'c', name: 'Ask for approval', icon: 'gate', state: 'wait' },
  { key: 'd', name: 'Post to Teams', icon: 'write', state: 'todo' },
]

const draw = (props: Partial<Parameters<typeof StepLine>[0]> = {}) => renderToStaticMarkup(<StepLine steps={STEPS} label="Last run" {...props} />)

const statesOf = (html: string) => [...html.matchAll(/data-state="(\w+)"/g)].map((match) => match[1])

function withReducedMotion(reduce: boolean): void {
  vi.stubGlobal('window', { matchMedia: (query: string) => ({ matches: reduce && query === '(prefers-reduced-motion: reduce)' }) })
}

afterEach(() => vi.unstubAllGlobals())

describe('the small step line', () => {
  it('is one picture with one name that says each step and where it stands, built from the steps', () => {
    const html = draw()
    expect(html).toMatch(/^<span class="[^"]*" role="img" aria-label="Last run: Done: Check releases, Done: Compare, Waiting for approval: Ask for approval, Not reached yet: Post to Teams">/)
    expect(html.match(/role="img"/g)).toHaveLength(1)
  })

  it('draws one circle per step, in order, each with its state', () => {
    expect(statesOf(draw())).toEqual(['done', 'done', 'wait', 'todo'])
  })

  it("draws a stopped step as stop and a step not reached as dashed, the sketch's two looks, and names them", () => {
    const html = draw({
      steps: [
        { key: 'a', name: 'Read', icon: 'read', state: 'err' },
        { key: 'b', name: 'Write', icon: 'write', state: 'skip' },
      ],
    })
    expect(statesOf(html)).toEqual(['err', 'skip'])
    expect(html).toContain('aria-label="Last run: Stopped here: Read, Skipped: Write"')
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

  it('holds the waiting ring still where many lines show at once, as Home’s board does', () => {
    withReducedMotion(false)
    expect(draw({ still: true })).not.toContain('data-ring')
  })

  it('says each state in the words the run line says it in, from one map, so no screen says waiting where another says Waiting for approval', () => {
    const html = draw()
    for (const state of ['done', 'wait', 'todo'] as const) expect(html).toContain(STEP_STATE_WORDS[state])
    expect(html).not.toMatch(/ waiting[,"]/)
  })

  it('says each state in a word of its own, for the places that read the steps one by one', () => {
    expect(STEP_STATE_WORDS.wait).toBe('Waiting for approval: ')
    expect(STEP_STATE_WORDS.err).toBe('Stopped here: ')
  })
})
