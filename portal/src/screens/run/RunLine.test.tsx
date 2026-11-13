import useCase from '@contracts/fixtures/builder/use-case.json'
import failure from '@contracts/fixtures/runs/failure.json'
import rejected from '@contracts/fixtures/runs/rejected.json'
import success from '@contracts/fixtures/runs/success.json'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { BlockKind } from '../../api/types'
import { StepLog } from './Chat'
import { Outcome } from './Outcome'
import { RunLine } from './RunLine'
import { emptyModel, foldWire, stationsOf, type ChatItem, type PlanBlock, type RunModel } from './runModel'
import { headlineOf, logRowsOf, settledOf, triggerWords, workingWords, type Schedule } from './words'

interface Raw {
  readonly run_id: string
  readonly seq: number
}

const PLAN: PlanBlock[] = useCase.plan.map((block) => ({ key: block.key, name: block.name, kind: block.kind as BlockKind }))
const NAMES: Record<string, string> = { alice: 'Alice', bob: 'Bob', carol: 'Carol' }
const nameOf = (id: string) => NAMES[id] ?? id
const QUICK = ['Not this week', 'Wrong version', 'Needs testing first']

function replay(raw: readonly Raw[], upTo = Infinity): RunModel {
  const kept = raw.filter((item) => item.seq <= upTo)
  return foldWire(emptyModel, kept, kept[0]?.run_id ?? '')
}

/** A time as the run's events carry it. */
const at = (iso: string) => Date.parse(iso) as ChatItem['at']

const text = (html: string) => html.replace(/<[^>]*>/g, ' ').replaceAll('&#x27;', "'").replace(/\s+/g, ' ').trim()

const SAME_DAY = new Date('2026-11-05T09:00:00Z')

function line(model: RunModel, { small = false, arrivedLive = null }: { small?: boolean; arrivedLive?: string | null } = {}): string {
  const stations = stationsOf(model, PLAN, 'Started by Alice')
  const settled = settledOf(model, nameOf, new Date((model.chat.at(-1)?.at ?? 0) + 3_600_000), QUICK)
  return renderToStaticMarkup(
    <MemoryRouter>
      <RunLine stations={stations} arrivedLive={arrivedLive} settled={settled} small={small} />
    </MemoryRouter>,
  )
}

/** Each link, in order, as the state it draws and whether it marches: "flow+" marches, "flow" holds still. */
function links(html: string): string[] {
  return [...html.matchAll(/<span class="[^"]*"( data-link="(\w+)")( data-march="true")?/g)].map((match) => `${match[2] ?? ''}${match[3] ? '+' : ''}`)
}

function withReducedMotion(reduce: boolean): void {
  vi.stubGlobal('window', { matchMedia: (query: string) => ({ matches: reduce && query === '(prefers-reduced-motion: reduce)' }) })
}

function stepItems(html: string): string[] {
  return [...html.matchAll(/<li class="[^"]*step[^"]*"[^>]*>[\s\S]*?<\/li>(?=<li class="[^"]*step|<\/ol>)/g)].map((match) => match[0])
}

function stepsSaid(html: string): string[] {
  return stepItems(html).map(text)
}

/** The run after its last event, a moment later: the line is drawn as the page first shows it. */
function shownAt(iso: string): void {
  vi.useFakeTimers({ now: new Date(iso) })
}

describe('the run line', () => {
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('draws only the workflow’s blocks, says each step’s state in words, and marks the gate as the current step while it waits', () => {
    const html = line(replay(success, 15))
    expect(stepsSaid(html)).toEqual(['Done: Started by Alice', 'Done: Read every source', 'Waiting for a yes: Ask for a yes', 'Not reached yet: Create Jira tickets'])
    expect(html.match(/aria-current="step"/g)).toHaveLength(1)
    expect(html).toMatch(/aria-current="step"[^>]*data-state="wait"/)
  })

  it('says how long the step at work has been working, once a second has passed', () => {
    shownAt('2026-11-03T02:14:00.400Z')
    expect(stepsSaid(line(replay(success, 6)))[1]).toBe('Now: Read every source Working…')
    expect(stepsSaid(line(replay(success, 6), { small: true }))[1]).toBe('Now: Read every source …')
    shownAt('2026-11-03T02:14:12.900Z')
    expect(stepsSaid(line(replay(success, 6)))[1]).toBe('Now: Read every source Working, 12 s')
    expect(stepsSaid(line(replay(success, 6), { small: true }))[1]).toBe('Now: Read every source 12 s')
    expect(line(replay(success, 6))).toMatch(/aria-current="step"[^>]*data-state="now"/)
  })

  it('reads all done once the ticket is written, puts the ticket under its step as a link, and says how the run settled', () => {
    const html = line(replay(success))
    expect(stepsSaid(html)).toEqual(['Done: Started by Alice', 'Done: Read every source', 'Done: Ask for a yes', 'Done: Create Jira tickets MOCK-142'])
    expect(stepItems(html)[3]).toMatch(/<a\b[^>]*href="\/jira\/MOCK-142"[^>]*>MOCK-142<\/a>/)
    expect(stepItems(html)[3], 'a key too long for its step is cut short on screen, never in its title').toContain('title="MOCK-142"')
    expect(text(html)).toContain('Done at 10:20 · MOCK-142 created after Bob’s yes')
  })

  it('gives every step done a tick, the stopped step a stop mark, and no other step a mark', () => {
    const marks = (html: string) => stepItems(html).map((item) => item.match(/_(tick|stopMark)_[^"]*" data-shown="true"/)?.[1] ?? '-')
    expect(marks(line(replay(success)))).toEqual(['tick', 'tick', 'tick', 'tick'])
    expect(marks(line(replay(success, 15)))).toEqual(['tick', 'tick', '-', '-'])
    expect(marks(line(replay(failure)))).toEqual(['tick', 'stopMark', '-', '-'])
    expect(marks(line(replay(rejected)))).toEqual(['tick', 'tick', '-', '-'])
  })

  it('shows a declined gate, a skipped write that says nothing was written, no step after them, and the settled line', () => {
    const html = line(replay(rejected))
    expect(stepsSaid(html)).toEqual(['Done: Started by Alice', 'Done: Read every source', 'Declined: Ask for a yes', 'Skipped: Create Jira tickets Nothing written'])
    expect(text(html)).toContain('Ended at 10:18 · Bob declined: wrong version. Nothing was written.')
    expect(html).not.toMatch(/created|href="\/jira\//)
  })

  it('marks where a failed run stopped, with no settled line', () => {
    const html = line(replay(failure))
    expect(stepsSaid(html)).toEqual(['Done: Started by Alice', 'Stopped here: Read every source', 'Not reached yet: Ask for a yes', 'Not reached yet: Create Jira tickets'])
    expect(html).not.toMatch(/Done at|Ended at/)
  })

  it('replays the work flowing into a stopped step when it first shows, and not with reduced motion', () => {
    withReducedMotion(false)
    const moving = line(replay(failure))
    expect(moving.match(/data-replay/g), 'the stopped step and the link into it').toHaveLength(2)
    expect(moving, 'the step still says it stopped').toMatch(/data-state="err" data-replay="true"/)
    expect(links(moving), 'the link still says it stopped').toEqual(['stop', 'todo', 'todo'])
    withReducedMotion(true)
    expect(line(replay(failure))).not.toContain('data-replay')
    withReducedMotion(false)
    expect(line(replay(success, 15)), 'a run that did not stop replays nothing').not.toContain('data-replay')
  })

  it('lands the step reached while the page watched, and no other', () => {
    const html = line(replay(success, 15), { arrivedLive: 'gate' })
    expect(html.match(/_arrive_/g)).toHaveLength(1)
    expect(html).toMatch(/class="[^"]*_arrive_[^"]*"[^>]*data-state="wait"/)
  })

  it('lets the keyboard reach the steps, so a line too long for its space can be scrolled', () => {
    for (const small of [false, true]) expect(line(replay(success), { small })).toMatch(/<div class="[^"]*_scroll_[^"]*" tabindex="0" role="group" aria-label="Steps">/)
  })

  it('puts the agent’s face above its step on the page, and no face in the side panel', () => {
    const faces = (html: string) => (html.match(/data-face=/g) ?? []).length
    expect(faces(line(replay(success)))).toBe(1)
    expect(faces(line(replay(success), { small: true }))).toBe(0)
  })
})

describe('the links between the steps', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  // Started by Alice, Read every source, Ask for a yes, Create Jira tickets: three links, each in the state of the step it leads into.
  it('march into the step at work', () => {
    withReducedMotion(false)
    expect(links(line(replay(success, 6)))).toEqual(['flow+', 'todo', 'todo'])
  })

  it('march slower, in amber, into a yes that waits, and are solid into the steps done', () => {
    withReducedMotion(false)
    expect(links(line(replay(success, 15)))).toEqual(['solid', 'wait+', 'todo'])
  })

  it('lead red into the step where the run stopped, and stay plain after it', () => {
    withReducedMotion(true)
    expect(links(line(replay(failure)))).toEqual(['stop', 'todo', 'todo'])
  })

  it('are solid all the way once the run is done', () => {
    withReducedMotion(false)
    expect(links(line(replay(success)))).toEqual(['solid', 'solid', 'solid'])
  })

  it('stay solid into a decline, and fade into the write it skipped', () => {
    withReducedMotion(false)
    expect(links(line(replay(rejected)))).toEqual(['solid', 'solid', 'dead'])
  })

  it('hold still with reduced motion, and keep the same look', () => {
    withReducedMotion(true)
    expect(links(line(replay(success, 6)))).toEqual(['flow', 'todo', 'todo'])
    expect(links(line(replay(success, 15)))).toEqual(['solid', 'wait', 'todo'])
  })

  it('grow the solid link into the step just finished as the run reaches the next one, and no other', () => {
    const html = line(replay(success, 15), { arrivedLive: 'gate' })
    expect(html.match(/_grow_/g)).toHaveLength(1)
    expect(stepItems(html)[0]).toMatch(/<span class="[^"]*_grow_[^"]*" data-link="solid"/)
  })

  it('draw the same steps and links in the side panel, small', () => {
    withReducedMotion(false)
    for (const model of [replay(success, 6), replay(success, 15), replay(failure), replay(rejected), replay(success)]) {
      const big = line(model)
      const small = line(model, { small: true })
      expect(links(small)).toEqual(links(big))
      expect(stepsSaid(small)).toEqual(stepsSaid(big).map((said) => said.replace('Working…', '…').replace('Working, ', '')))
    }
  })
})

describe('the words on the line', () => {
  const run = (trigger: 'person' | 'schedule') => ({ trigger, startedBy: 'alice' })

  it('start with who started the run, or with the schedule that did', () => {
    const friday8 = '2026-11-13T00:00:05Z'
    const sg = (day: Schedule['day'], at: string): Schedule => ({ day, at, time_zone: 'Asia/Singapore' })
    expect(triggerWords(run('person'), null, nameOf, friday8)).toBe('Started by Alice')
    expect(triggerWords(run('schedule'), sg('every_day', '08:00'), nameOf, friday8)).toBe('Daily 8:00')
    expect(triggerWords(run('schedule'), sg('monday', '09:00'), nameOf, '2026-11-16T01:00:02Z')).toBe('Mon 9:00')
    expect(triggerWords(run('schedule'), sg('weekdays', '07:30'), nameOf, '2026-11-12T23:31:00Z')).toBe('Weekdays 7:30')
    expect(triggerWords(run('schedule'), { day: 'every_day', at: '08:00', time_zone: 'Europe/London' }, nameOf, '2026-11-13T08:00:03Z'), 'in the schedule’s own zone').toBe('Daily 8:00')
    expect(triggerWords(run('schedule'), null, nameOf, friday8), 'a schedule that is gone is not guessed').toBe('On schedule')
  })

  it('say only "On schedule" for a run the schedule today would not have started', () => {
    const sg = (day: Schedule['day'], at: string): Schedule => ({ day, at, time_zone: 'Asia/Singapore' })
    expect(triggerWords(run('schedule'), sg('every_day', '09:00'), nameOf, '2026-11-13T00:00:05Z'), 'the time changed since').toBe('On schedule')
    expect(triggerWords(run('schedule'), sg('monday', '08:00'), nameOf, '2026-11-13T00:00:05Z'), 'the day changed since').toBe('On schedule')
    expect(triggerWords(run('schedule'), sg('weekdays', '08:00'), nameOf, '2026-11-14T00:00:05Z'), 'a Saturday is not a weekday').toBe('On schedule')
  })

  it('count the seconds a step has worked, then the minutes, then the hours', () => {
    const since = at('2026-11-03T02:14:00Z')
    const after = (ms: number) => since + ms
    expect([0, 999, 1000, 12_400, 59_999, 60_000, 185_000, 3_599_999, 7_300_000].map((ms) => workingWords(since, after(ms), false))).toEqual([
      'Working…',
      'Working…',
      'Working, 1 s',
      'Working, 12 s',
      'Working, 59 s',
      'Working, 1 min',
      'Working, 3 min',
      'Working, 59 min',
      'Working, 2 h',
    ])
    expect([0, 12_400, 185_000].map((ms) => workingWords(since, after(ms), true))).toEqual(['…', '12 s', '3 min'])
  })

  it('settle a done run on its time, its tickets and who said yes', () => {
    expect(settledOf(replay(success), nameOf, new Date('2026-11-03T09:00:00Z'), QUICK)).toEqual({ tone: 'ok', text: 'Done at 10:20 · MOCK-142 created after Bob’s yes' })
    expect(settledOf(replay(success), nameOf, new Date('2026-11-04T09:00:00Z'), QUICK), 'another day says its day').toEqual({
      tone: 'ok',
      text: 'Done on Tue 3 Nov at 10:20 · MOCK-142 created after Bob’s yes',
    })
    const twoYeses = { ...replay(success), approvedBy: ['carol', 'bob'] }
    expect(settledOf(twoYeses, nameOf, new Date('2026-11-03T09:00:00Z'), QUICK)?.text).toBe('Done at 10:20 · MOCK-142 created after Carol and Bob said yes')
    const page = { ...replay(success), written: [{ connector: 'confluence', operation: 'update_page', ref: 'PAGE-9' }] }
    expect(settledOf(page, nameOf, new Date('2026-11-03T09:00:00Z'), QUICK)?.text).toBe('Done at 10:20 · PAGE-9 written after Bob’s yes')
    const noKey = { ...replay(success), written: [{ connector: 'jira', operation: 'create_ticket', ref: '' }] }
    expect(settledOf(noKey, nameOf, new Date('2026-11-03T09:00:00Z'), QUICK)?.text, 'a write with no key is counted, never shown as an empty key').toBe('Done at 10:20 · 1 ticket created after Bob’s yes')
    expect(line(noKey), 'and puts no empty chip under the write').not.toMatch(/_chip_/)
  })

  it('settle a run with nothing to write as nothing new', () => {
    const done = { ...(success.at(-1) ?? {}), seq: 9, data: { outcome: 'nothing_to_write' } }
    const model = foldWire(replay(success, 8), [done], success[0]?.run_id ?? '')
    expect(settledOf(model, nameOf, new Date('2026-11-03T09:00:00Z'), QUICK)).toEqual({ tone: 'ok', text: 'Done at 10:20 · Nothing new' })
  })

  it('settle a declined run on who declined and why, keeping a reason the Approver typed as they typed it', () => {
    const declined = replay(rejected)
    const said = (model: RunModel) => settledOf(model, nameOf, SAME_DAY, QUICK)?.text
    expect(settledOf(declined, nameOf, SAME_DAY, QUICK)).toEqual({ tone: 'off', text: 'Ended at 10:18 · Bob declined: wrong version. Nothing was written.' })
    expect(said({ ...declined, declineReason: 'FastAPI 0.121 breaks our build.' })).toBe('Ended at 10:18 · Bob declined: FastAPI 0.121 breaks our build. Nothing was written.')
    expect(said({ ...declined, declineReason: null })).toBe('Ended at 10:18 · Bob declined. Nothing was written.')
    expect(said({ ...declined, approvedBy: ['carol'] })).toBe('Ended at 10:18 · Carol said yes, then Bob declined: wrong version. Nothing was written.')
  })

  it('leave a run that is still going, or stopped, unsettled', () => {
    for (const model of [replay(success, 6), replay(success, 15), replay(success, 16), replay(failure)]) expect(settledOf(model, nameOf, SAME_DAY, QUICK)).toBeNull()
  })
})

describe('the Step by step', () => {
  function steps(items: RunModel['chat'], loadedUpTo = 99): string {
    return renderToStaticMarkup(
      <MemoryRouter>
        <StepLog rows={logRowsOf(items, nameOf, QUICK)} loadedUpTo={loadedUpTo} />
      </MemoryRouter>,
    )
  }
  const rowsOf = (html: string) =>
    [...html.matchAll(/<li[^>]*>([\s\S]*?)<\/li>/g)].map((match) => {
      const row = match[1] ?? ''
      return `${row.match(/<time[^>]*>([^<]*)<\/time>/)?.[1] ?? '-'} ${text(row.replace(/<time[\s\S]*?<\/time>/, ''))}`
    })

  it('tells a done run one sentence a row, with the gate’s words, and never repeats the ticket the settled line names', () => {
    expect(rowsOf(steps(replay(success).chat))).toEqual([
      '10:14:00 Alice started the run.',
      '10:14:02 Planner Please check LangGraph for new releases.',
      '10:14:05 Version checker LangGraph has a new release: 1.2.16. I suggest one ticket.',
      "10:14:05 Planner Agreed. I'll draft one ticket for an Approver to check.",
      '10:14:08 Asked an Approver for a yes in Teams.',
      '10:20:23 Bob said yes.',
      '10:20:26 Created MOCK-142 in Jira.',
    ])
    expect(steps(replay(success).chat)).not.toMatch(/n8n|execution|workflow step|room lead|release checker|use case/i)
  })

  it('ends a declined run on one row that says who declined and that nothing was written, and never says Done', () => {
    const said = rowsOf(steps(replay(rejected).chat))
    expect(said.at(-1)).toBe('10:18:11 Bob declined: wrong version. Nothing was written.')
    expect(said.filter((row) => /declined/.test(row))).toHaveLength(1)
    expect(said.join(' ')).not.toMatch(/Done|created/)
  })

  it('lets the agent that failed say so in red', () => {
    const html = steps(replay(failure).chat)
    expect(html).toMatch(/class="[^"]*bad[^"]*"/)
    expect(text(html)).toContain('The run stopped. Nothing was written.')
  })

  it('animates only what arrived while the page watched', () => {
    const model = replay(success, 9)
    const animated = (html: string) => (html.match(/class="[^"]*_in_[^"]*"/g) ?? []).length
    expect(animated(steps(model.chat, model.seq))).toBe(0)
    expect(animated(steps(model.chat, 7))).toBe(2)
  })

  it('says the day again on a row from another day', () => {
    const html = steps([
      { kind: 'started', seq: 1, at: at('2026-10-27T00:00:00Z'), by: 'alice', trigger: 'person' },
      { kind: 'decided', seq: 2, at: at('2026-10-27T15:59:00Z'), by: 'bob', verdict: 'approve', step: null },
      { kind: 'declined', seq: 3, at: at('2026-10-27T16:01:00Z'), record: { by: 'bob', approvedBy: [], reason: null } },
    ])
    expect([...html.matchAll(/<time[^>]*dateTime="([^"]+)"[^>]*>([^<]*)<\/time>/gi)].map((match) => `${match[1] ?? ''} ${match[2] ?? ''}`)).toEqual([
      '2026-10-27T00:00:00.000Z 8:00:00',
      '2026-10-27T15:59:00.000Z 23:59:00',
      '2026-10-27T16:01:00.000Z Wed 28 Oct, 0:01:00',
    ])
  })

  it('lets the gate’s row take focus after a decision', () => {
    expect(steps(replay(success).chat)).toMatch(/tabindex="-1" data-gate-said="16"/)
  })
})

describe('what stays after a finished run', () => {
  it('keeps what happens next after a decline, and says nothing of the ticket or the reason the settled line gives', () => {
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <Outcome declinedNext="Change what it does, or run the test again." />
      </MemoryRouter>,
    )
    expect(text(html)).toContain('Change what it does, or run the test again.')
    expect(html).not.toMatch(/created|Declined by|href="\/jira\//)
  })
})

describe('the heading', () => {
  it('says what the run needs or did', () => {
    const head = (model: RunModel) => headlineOf(model, stationsOf(model, PLAN, 'Started by Alice'), null)
    expect(head(replay(success, 6))).toMatchObject({ text: 'The agents are working', pill: { label: 'Running' } })
    expect(head(replay(success, 15))).toMatchObject({ text: 'Waiting for a yes', pill: { label: 'Waiting for a yes', tone: 'wait' } })
    expect(head(replay(success))).toMatchObject({ text: '1 ticket created in Jira', pill: { label: 'Done', tone: 'ok' } })
    expect(head(replay(rejected))).toMatchObject({ text: 'Declined, nothing was written', pill: { label: 'Declined' } })
    expect(head(replay(failure))).toMatchObject({ text: 'Stopped at Read every source', pill: { label: 'Stopped', tone: 'bad' } })
    const early = { ...replay(failure, 2), failedAt: { at: 'planner' }, phase: { state: 'failed', stage: 'pending', reason: 'DispatchFailed', retryable: true, message: '' } } as const
    expect(head(early), 'a stop before any agent began names the step it never reached').toMatchObject({ text: 'Stopped before Read every source' })
  })
})

describe('ticket keys on the run page', () => {
  // The project is a setting, so the keys the run holds are not always MOCK.
  const ops = JSON.parse(JSON.stringify(success).replaceAll('MOCK-142', 'OPS-142')) as Raw[]
  const link = (key: string) => new RegExp(`<a\\b[^>]*href="/jira/${key}"[^>]*>(?:(?!</a>)[\\s\\S])*${key}`)

  function chatHtml(items: RunModel['chat']): string {
    return renderToStaticMarkup(
      <MemoryRouter>
        <StepLog rows={logRowsOf(items, nameOf, QUICK)} loadedUpTo={99} />
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

  it('links a written ticket to the address the platform gave', () => {
    const real = JSON.parse(JSON.stringify(ops).replaceAll('/jira/OPS-142', 'https://jira.real.test/browse/OPS-142')) as Raw[]
    expect(chatHtml(replay(real).chat)).toContain('href="https://jira.real.test/browse/OPS-142"')
  })
})
