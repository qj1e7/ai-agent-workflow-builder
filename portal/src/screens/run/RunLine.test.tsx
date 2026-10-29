import useCase from '@contracts/fixtures/builder/use-case.json'
import failure from '@contracts/fixtures/runs/failure.json'
import rejected from '@contracts/fixtures/runs/rejected.json'
import success from '@contracts/fixtures/runs/success.json'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { BlockKind } from '../../api/types'
import { Chat } from './Chat'
import { RunLine } from './RunLine'
import { emptyModel, foldWire, reachOf, stationsOf, type PlanBlock, type RunModel } from './runModel'
import { headlineOf, writeLabel } from './words'

interface Raw {
  readonly run_id: string
  readonly seq: number
}

const PLAN: PlanBlock[] = useCase.plan.map((block) => ({ name: block.name, kind: block.kind as BlockKind }))
const NAMES: Record<string, string> = { alice: 'Alice', bob: 'Bob' }
const nameOf = (id: string) => NAMES[id] ?? id

function replay(raw: readonly Raw[], upTo = Infinity): RunModel {
  const kept = raw.filter((item) => item.seq <= upTo)
  return foldWire(emptyModel, kept, kept[0]?.run_id ?? '')
}

const text = (html: string) => html.replace(/<[^>]*>/g, ' ').replaceAll('&#x27;', "'").replace(/\s+/g, ' ').trim()

function line(model: RunModel): string {
  const stations = stationsOf(model, PLAN, writeLabel)
  return renderToStaticMarkup(<RunLine stations={stations} reach={reachOf(stations)} arrivedLive={null} startedAt="Tue 10:14" nameOf={nameOf} />)
}

function stepsSaid(html: string): string[] {
  return [...html.matchAll(/<li class="[^"]*station[^"]*"[^>]*>([\s\S]*?)<\/li>/g)].map((match) => text(match[1] ?? ''))
}

describe('the run line', () => {
  it('says each step’s state in words while the run waits for a yes, and marks the gate as the current step', () => {
    const html = line(replay(success, 15))
    expect(stepsSaid(html)).toEqual([
      'A Done: Started Tue 10:14',
      'Done: Pick agents',
      'Done: Read every source Version checker',
      'Approval gate Waiting for a yes',
      'Not reached yet: Create Jira tickets',
      'Not reached yet: Done',
    ])
    expect(html.match(/aria-current="step"/g)).toHaveLength(1)
    expect(html).toMatch(/aria-current="step"[^>]*data-state="wait"/)
  })

  it('marks the step running now', () => {
    const html = line(replay(success, 6))
    expect(stepsSaid(html)[2]).toBe('Now: Read every source Version checker')
    expect(html).toMatch(/aria-current="step"[^>]*data-state="now"/)
  })

  it('reads all done once the ticket is written', () => {
    expect(stepsSaid(line(replay(success)))).toEqual([
      'A Done: Started Tue 10:14',
      'Done: Pick agents',
      'Done: Read every source Version checker',
      'Done: Approval gate Approved',
      'Done: Create Jira tickets',
      'Done: Done',
    ])
  })

  it('shows a declined gate and a write that was not needed', () => {
    expect(stepsSaid(line(replay(rejected))).slice(3)).toEqual(['Approval gate Declined', 'Create Jira tickets Not needed', 'Done: Done'])
  })

  it('marks where a failed run stopped', () => {
    expect(stepsSaid(line(replay(failure))).slice(2)).toEqual([
      'Read every source Stopped here',
      'Not reached yet: Approval gate',
      'Not reached yet: Create Jira tickets',
      'Not reached yet: Done',
    ])
  })

  it('lands the step reached while the page watched, and no other', () => {
    const model = replay(success, 15)
    const stations = stationsOf(model, PLAN, writeLabel)
    const html = renderToStaticMarkup(<RunLine stations={stations} reach={reachOf(stations)} arrivedLive="gate" startedAt="" nameOf={nameOf} />)
    expect(html.match(/arrive/g)).toHaveLength(1)
    expect(html).toMatch(/class="[^"]*arrive[^"]*"[^>]*data-state="wait"/)
  })

  it('sets how far the line reaches through a style property, never a style attribute string from data', () => {
    expect(line(replay(success, 15))).toContain('--f:0.6')
  })
})

describe('the chat', () => {
  function chat(model: RunModel, loadedUpTo = model.seq): string {
    return renderToStaticMarkup(<Chat items={model.chat} loadedUpTo={loadedUpTo} nameOf={nameOf} trigger="person" last={null} />)
  }

  it('tells a done run with the gate’s words in its own markers', () => {
    const said = text(chat(replay(success)))
    expect(said).toContain('Alice started the run.')
    expect(said).toContain('Version checker joined')
    expect(said).toContain('Asked for a yes in Teams, in CODESparks Ops.')
    expect(said).toContain('Bob approved.')
    expect(said).toContain('Created MOCK-142 in Jira.')
    expect(said).toContain('Done. 1 ticket created.')
    expect(said).not.toMatch(/n8n|execution|workflow step|room lead|release checker|use case/i)
  })

  it('says who declined and that nothing was written', () => {
    const said = text(chat(replay(rejected)))
    expect(said).toContain('Bob declined.')
    expect(said).toContain('Done. Nothing was written.')
  })

  it('lets the agent that failed say so in a red bubble', () => {
    const html = chat(replay(failure))
    expect(html).toMatch(/class="[^"]*bad[^"]*"/)
    expect(text(html)).toContain('The run stopped. Nothing was written.')
  })

  it('animates only what arrived while the page watched', () => {
    const model = replay(success, 9)
    const animated = (html: string) => (html.match(/class="[^"]*_in_[^"]*"/g) ?? []).length
    expect(animated(chat(model))).toBe(0)
    expect(animated(chat(model, 7))).toBe(2)
  })

  it('lets the gate’s lines take focus after a decision', () => {
    expect(chat(replay(success))).toMatch(/tabindex="-1" data-gate-said="16"/)
  })
})

describe('the heading', () => {
  it('says what the run needs or did', () => {
    const head = (model: RunModel) => headlineOf(model, stationsOf(model, PLAN, writeLabel), null)
    expect(head(replay(success, 6))).toMatchObject({ text: 'The agents are working', pill: { label: 'Working' } })
    expect(head(replay(success, 15))).toMatchObject({ text: 'Waiting for a yes', pill: { label: 'Waiting for a yes', tone: 'wait' } })
    expect(head(replay(success))).toMatchObject({ text: '1 ticket created in Jira', pill: { label: 'Done', tone: 'ok' } })
    expect(head(replay(rejected))).toMatchObject({ text: 'Declined, nothing was written', pill: { label: 'Declined' } })
    expect(head(replay(failure))).toMatchObject({ text: 'Stopped at Read every source', pill: { label: 'Stopped', tone: 'bad' } })
  })
})
