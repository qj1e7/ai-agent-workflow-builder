import useCase from '@contracts/fixtures/builder/use-case.json'
import failure from '@contracts/fixtures/runs/failure.json'
import rejected from '@contracts/fixtures/runs/rejected.json'
import success from '@contracts/fixtures/runs/success.json'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { BlockKind } from '../../api/types'
import { Chat } from './Chat'
import { Outcome } from './Outcome'
import { RunLine } from './RunLine'
import { emptyModel, foldWire, stationsOf, type ChatItem, type PlanBlock, type RunModel } from './runModel'
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

/** A time as the run's events carry it. */
const at = (iso: string) => Date.parse(iso) as ChatItem['at']

const text = (html: string) => html.replace(/<[^>]*>/g, ' ').replaceAll('&#x27;', "'").replace(/\s+/g, ' ').trim()

function line(model: RunModel, { small = false, arrivedLive = null }: { small?: boolean; arrivedLive?: string | null } = {}): string {
  const stations = stationsOf(model, PLAN, writeLabel)
  return renderToStaticMarkup(<RunLine stations={stations} arrivedLive={arrivedLive} startedAt="Tue 10:14" nameOf={nameOf} small={small} />)
}

/** Each link, in order, as the state it draws and whether it marches: "flow+" marches, "flow" holds still. */
function links(html: string): string[] {
  return [...html.matchAll(/<span class="[^"]*"( data-link="(\w+)")( data-march="true")?/g)].map((match) => `${match[2] ?? ''}${match[3] ? '+' : ''}`)
}

function withReducedMotion(reduce: boolean): void {
  vi.stubGlobal('window', { matchMedia: (query: string) => ({ matches: reduce && query === '(prefers-reduced-motion: reduce)' }) })
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

  it('shows a declined gate, a write that says nothing was written, and a run that ended without a tick', () => {
    const html = line(replay(rejected))
    expect(stepsSaid(html).slice(3)).toEqual(['Approval gate Declined', 'Create Jira tickets Nothing written', 'Done: Ended'])
    const ended = [...html.matchAll(/<li\b[\s\S]*?<\/li>/g)].map((match) => match[0]).at(-1) ?? ''
    expect(ended).not.toContain('<svg')
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
    const html = line(replay(success, 15), { arrivedLive: 'gate' })
    expect(html.match(/arrive/g)).toHaveLength(1)
    expect(html).toMatch(/class="[^"]*arrive[^"]*"[^>]*data-state="wait"/)
  })
})

describe('the links between the steps', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  // Started, Pick agents, Read every source, Approval gate, Create Jira tickets, Done: five links, each in the state of the step it leads into.
  it('march into the step at work, and are solid into the steps done', () => {
    withReducedMotion(false)
    expect(links(line(replay(success, 6)))).toEqual(['solid', 'flow+', 'todo', 'todo', 'todo'])
  })

  it('march slower, in amber, into a yes that waits', () => {
    withReducedMotion(false)
    expect(links(line(replay(success, 15)))).toEqual(['solid', 'solid', 'wait+', 'todo', 'todo'])
  })

  it('lead red into the step where the run stopped, and stay plain after it', () => {
    withReducedMotion(false)
    expect(links(line(replay(failure)))).toEqual(['solid', 'stop', 'todo', 'todo', 'todo'])
  })

  it('are solid all the way once the run is done', () => {
    withReducedMotion(false)
    expect(links(line(replay(success)))).toEqual(['solid', 'solid', 'solid', 'solid', 'solid'])
  })

  it('fade into a step that was not needed, and stay solid into a decline', () => {
    withReducedMotion(false)
    expect(links(line(replay(rejected)))).toEqual(['solid', 'solid', 'solid', 'dead', 'solid'])
  })

  it('hold still with reduced motion, and keep the same look', () => {
    withReducedMotion(true)
    expect(links(line(replay(success, 6)))).toEqual(['solid', 'flow', 'todo', 'todo', 'todo'])
    expect(links(line(replay(success, 15)))).toEqual(['solid', 'solid', 'wait', 'todo', 'todo'])
  })

  it('grow the solid link into the step just finished as the run reaches the next one, and no other', () => {
    const html = line(replay(success, 15), { arrivedLive: 'gate' })
    expect(html.match(/_grow_/g)).toHaveLength(1)
    expect(html).toMatch(/data-state="done"><span class="[^"]*_grow_[^"]*" data-link="solid"[\s\S]*?Read every source/)
  })

  it('draw the same steps and links in the side panel, small and without faces', () => {
    withReducedMotion(false)
    for (const model of [replay(success, 6), replay(success, 15), replay(failure), replay(rejected), replay(success)]) {
      const big = line(model)
      const small = line(model, { small: true })
      expect(links(small)).toEqual(links(big))
      expect(stepsSaid(small)).toEqual(stepsSaid(big).map((said) => said.replace(/^A /, '')))
      expect(small).not.toMatch(/_who_|<svg[^>]*role="img"/)
    }
  })
})

describe('the chat', () => {
  function chat(model: RunModel, loadedUpTo = model.seq): string {
    return renderToStaticMarkup(
      <MemoryRouter>
        <Chat items={model.chat} loadedUpTo={loadedUpTo} nameOf={nameOf} trigger="person" last={null} />
      </MemoryRouter>,
    )
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

  it('says who declined, and ends on the declined record, never on Done', () => {
    const said = text(chat(replay(rejected)))
    expect(said).toContain('Bob declined.')
    expect(said).toContain('Declined by Bob. Nothing was written. Reason: Wrong version. The run ended.')
    expect(said).not.toMatch(/Done\.|created/)
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

  it('gives each entry its time, the first with its day, and none to the line that says who joined', () => {
    const entries = [...chat(replay(success)).matchAll(/<li[^>]*>([\s\S]*?)<\/li>/g)].map((match) => {
      const html = match[1] ?? ''
      return `${html.match(/<time[^>]*>([^<]*)<\/time>/)?.[1] ?? '-'} ${text(html.replace(/<time[\s\S]*?<\/time>/, ''))}`
    })
    expect(entries).toEqual([
      'Tue 3 Nov, 10:14 Alice started the run.',
      '- Version checker joined',
      '10:14 Planner Please check LangGraph for new releases.',
      '10:14 Version checker LangGraph has a new release: 1.2.16. I suggest one ticket.',
      "10:14 Planner Agreed. I'll draft one ticket for an Approver to check.",
      '10:14 Asked for a yes in Teams, in CODESparks Ops. Nothing is written until an Approver says yes.',
      '10:20 Bob approved.',
      '10:20 Created MOCK-142 in Jira.',
      '10:20 Done. 1 ticket created.',
    ])
  })

  it('says the day again on an entry from another day', () => {
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <Chat
          items={[
            { kind: 'started', seq: 1, at: at('2026-10-27T00:00:00Z'), by: 'alice', trigger: 'person' },
            { kind: 'decided', seq: 2, at: at('2026-10-27T15:59:00Z'), by: 'bob', verdict: 'approve', step: null },
            { kind: 'declined', seq: 3, at: at('2026-10-27T16:01:00Z'), record: { by: 'bob', approvedBy: [], reason: null } },
          ]}
          loadedUpTo={9}
          nameOf={nameOf}
          trigger="person"
          last={null}
        />
      </MemoryRouter>,
    )
    expect([...html.matchAll(/<time[^>]*dateTime="([^"]+)"[^>]*>([^<]*)<\/time>/gi)].map((match) => `${match[1] ?? ''} ${match[2] ?? ''}`)).toEqual([
      '2026-10-27T00:00:00.000Z Tue 27 Oct, 8:00',
      '2026-10-27T15:59:00.000Z 23:59',
      '2026-10-27T16:01:00.000Z Wed 28 Oct, 0:01',
    ])
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

describe('ticket keys on the run page', () => {
  // The project is a setting, so the keys the run holds are not always MOCK.
  const ops = JSON.parse(JSON.stringify(success).replaceAll('MOCK-142', 'OPS-142')) as Raw[]
  const link = (key: string) => new RegExp(`<a\\b[^>]*href="/jira/${key}"[^>]*>(?:(?!</a>)[\\s\\S])*${key}`)

  function chatHtml(items: RunModel['chat']): string {
    return renderToStaticMarkup(
      <MemoryRouter>
        <Chat items={items} loadedUpTo={99} nameOf={nameOf} trigger="person" last={null} />
      </MemoryRouter>,
    )
  }

  it('links the key a Jira write names, in any project', () => {
    expect(chatHtml(replay(ops).chat)).toMatch(link('OPS-142'))
  })

  it('does not link a key in a write to some other system, or key-like words in what an agent said', () => {
    const html = chatHtml([
      { kind: 'written', seq: 1, at: at('2026-11-03T02:14:00Z'), connector: 'confluence', operation: 'update_page', refs: ['OPS-9'] },
      { kind: 'said', seq: 2, at: at('2026-11-03T02:14:00Z'), speaker: { id: 'version_checker', display: 'Version checker' }, text: 'UTF-8 and CVE-2024-1234 and OPS-9', bad: false },
    ])
    expect(html).not.toContain('href="/jira/')
  })

  it('links a written ticket to the address the platform gave, in the chat and in the Done panel', () => {
    const real = JSON.parse(JSON.stringify(ops).replaceAll('/jira/OPS-142', 'https://jira.real.test/browse/OPS-142')) as Raw[]
    const model = replay(real)
    expect(chatHtml(model.chat)).toContain('href="https://jira.real.test/browse/OPS-142"')
    const done = renderToStaticMarkup(
      <MemoryRouter>
        <Outcome model={model} nameOf={nameOf} />
      </MemoryRouter>,
    )
    expect(done).toContain('href="https://jira.real.test/browse/OPS-142"')
  })

  it('links the ticket chip in the Done panel, and not a written reference from another system', () => {
    const outcome = (model: RunModel) =>
      renderToStaticMarkup(
        <MemoryRouter>
          <Outcome model={model} nameOf={nameOf} />
        </MemoryRouter>,
      )
    expect(outcome(replay(ops))).toMatch(link('OPS-142'))
    const confluence = { ...replay(ops), written: [{ connector: 'confluence', operation: 'update_page', ref: 'PAGE-9' }] }
    expect(outcome(confluence)).not.toContain('href="/jira/')
    const empty = { ...replay(ops), written: [{ connector: 'jira', operation: 'create_ticket', ref: '' }] }
    expect(outcome(empty)).not.toContain('href="/jira/"')
  })
})
