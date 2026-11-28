/// <reference types="node" />
import { readFileSync } from 'node:fs'
import useCase from '@contracts/fixtures/builder/use-case.json'
import failure from '@contracts/fixtures/runs/failure.json'
import success from '@contracts/fixtures/runs/success.json'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { BlockKind } from '../../api/types'
import { RunStage } from './RunStage'
import { emptyModel, foldWire, stationsOf, type Phase, type PlanBlock, type RunModel, type Station } from './runModel'

interface Raw {
  readonly run_id: string
  readonly seq: number
}

const PLAN: PlanBlock[] = useCase.plan.map((block) => ({ key: block.key, name: block.name, kind: block.kind as BlockKind }))

function replay(raw: readonly Raw[], upTo = Infinity): RunModel {
  const kept = raw.filter((item) => item.seq <= upTo)
  return foldWire(emptyModel, kept, kept[0]?.run_id ?? '')
}

const stationsAt = (raw: readonly Raw[], upTo = Infinity): Station[] => stationsOf(replay(raw, upTo), PLAN, 'Started by Alice')

function stage(stations: readonly Station[], phase: Phase['state'] = 'succeeded', stopNote: string | null = null): string {
  return renderToStaticMarkup(
    <MemoryRouter>
      <RunStage stations={stations} arrivedLive={null} phase={phase} stopNote={stopNote} />
    </MemoryRouter>,
  )
}

function withReducedMotion(reduce: boolean): void {
  vi.stubGlobal('window', { matchMedia: (query: string) => ({ matches: reduce && query === '(prefers-reduced-motion: reduce)' }) })
}

const text = (html: string) => html.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim()
const states = (html: string) => [...html.matchAll(/<li [^>]*data-state="(\w+)"/g)].map((match) => match[1])

afterEach(() => vi.unstubAllGlobals())

describe('the stage on a run that wrote its ticket', () => {
  const html = stage(stationsAt(success))

  it('draws the Planner above the steps, with its name', () => {
    expect(html).toContain('data-face="visor"')
    expect(text(html)).toContain('Planner')
  })

  it('lists every step, each with its state in the step line\'s words for a screen reader and none on screen', () => {
    expect(html).toContain('aria-label="Steps of this run"')
    expect(states(html)).toEqual(['done', 'done', 'done', 'done'])
    expect(html.match(/class="visually-hidden">Done: </g)).toHaveLength(4)
    expect(html).not.toMatch(/Waits for approval|At work/)
  })

  it('puts an Orb on each agent step and the icon on the others', () => {
    expect(html.match(/data-face="orb"/g)).toHaveLength(1)
  })

  it('draws the Planner smiling, since the run succeeded, and not for a run that was declined or expired', () => {
    expect(html).toMatch(/data-face="visor" data-state="success"/)
    for (const phase of ['rejected', 'expired', 'lost', 'skipped'] as const) expect(stage(line('done', 'done', 'no', 'skip'), phase)).toMatch(/data-face="visor" data-state="idle"/)
  })
})

/** A line of four steps in the given states, as the run line builds it from a finished run. */
function line(...states: Station['state'][]): Station[] {
  return stationsAt(success).map((station, index) => ({ ...station, state: states[index] ?? 'todo', face: 'idle', under: null }))
}

describe('the stage on a run that waits for approval', () => {
  const html = stage(line('done', 'done', 'wait', 'todo'), 'awaiting_approval')

  it('names the gate as waiting for a screen reader only, since the pill says it, marks it the current step, and draws the gate wire in amber', () => {
    expect(states(html)).toEqual(['done', 'done', 'wait', 'todo'])
    expect(html).toContain('class="visually-hidden">Waiting for approval: ')
    expect(text(html.replace(/<span class="visually-hidden">[^<]*<\/span>/g, ''))).not.toMatch(/Waits for approval|Waiting for approval/)
    expect(html).toContain('data-hand="gate"')
    expect(html).toMatch(/<li [^>]*data-state="wait"[^>]*aria-current="step"|<li [^>]*aria-current="step"[^>]*data-state="wait"/)
  })

  it('joins the steps with the step line\'s links: solid, then dashes into the gate that waits, then dots', () => {
    expect([...html.matchAll(/data-link="(\w+)"/g)].map((match) => match[1])).toEqual(['solid', 'wait', 'todo'])
  })

  it('draws the Planner looking up with a clock', () => {
    expect(html).toMatch(/data-face="visor" data-state="waiting"/)
  })
})

describe('the stage on a run that stopped', () => {
  const stopped = line('done', 'err', 'todo', 'todo')

  it('marks the stopped step, shows the reason under it instead of a state word, and keeps the Planner wire violet', () => {
    const html = stage(stopped, 'failed', 'GitHub did not answer.')
    expect(states(html)).toEqual(['done', 'err', 'todo', 'todo'])
    expect(html).toContain('class="visually-hidden">Stopped here: ')
    expect(text(html)).toContain('GitHub did not answer.')
    expect(html).toContain('data-hand="ai"')
    expect(html).not.toContain('data-hand="cut"')
    expect(html).toMatch(/data-face="visor" data-state="error"/)
  })

  it('opens with the work flowing into the stop, as the run line does', () => {
    withReducedMotion(false)
    const glows = [...stage(stopped, 'failed').matchAll(/data-glow="([^"]+)"/g)].map((match) => match[1])
    expect(glows).toEqual(['track:1', 'plan:1'])
  })

  it('draws the stop from a real failed run too', () => {
    expect(states(stage(stationsAt(failure)))).toContain('err')
  })
})

describe('a line longer than six steps', () => {
  it('falls back to the plain step line', () => {
    const six = stationsAt(success)
    const seven = Array.from({ length: 7 }, (_, index) => ({ ...six[index % six.length]!, key: `s${index}` }))
    const html = stage(seven)
    expect(html).not.toContain('data-stage')
    expect(html).toContain('aria-label="Steps of this run"')
    expect(html).not.toContain('data-face="visor"')
  })
})

describe('motion', () => {
  const stations = stationsAt(success)

  it('plays the hand-offs and the opening when motion is allowed', () => {
    withReducedMotion(false)
    const html = stage(stations)
    expect(html).toContain('data-glow=')
    expect(html).toContain('data-opening="true"')
  })

  it('draws no glow and no opening with reduced motion, and the same steps and words', () => {
    withReducedMotion(false)
    const moving = stage(stations)
    withReducedMotion(true)
    const still = stage(stations)
    expect(still).not.toContain('data-glow=')
    expect(still).not.toContain('data-opening')
    expect(still).not.toContain('data-ring')
    expect(states(still)).toEqual(states(moving))
    expect(text(still)).toBe(text(moving))
  })

  it('pulses only the waiting gate, and never under reduced motion', () => {
    const css = readFileSync(new URL('./RunStage.module.css', import.meta.url), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '')
    const infinite = [...css.matchAll(/([^{}]+)\{[^}]*animation:[^;}]*infinite[^}]*\}/g)].map((match) => match[1]?.trim())
    expect(infinite).toEqual(['.node[data-ring]::after'])
    expect(css, 'a face works a few times, then rests').toMatch(/\[data-face\][\s\S]*animation-iteration-count: 2 !important/)
    expect(css).toMatch(/@media \(prefers-reduced-motion: reduce\)[\s\S]*\.node::after[\s\S]*animation: none !important/)
  })
})
