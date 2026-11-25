import useCase from '@contracts/fixtures/builder/use-case.json'
import failure from '@contracts/fixtures/runs/failure.json'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { BlockKind } from '../../api/types'
import { FixCrew } from './FixCrew'
import { emptyModel, foldWire, stationsOf, type PlanBlock, type RunModel } from './runModel'
import { troubleFaceOf } from './troubleFace'
import { lineOf, logRowsOf } from './words'

const RUN = 'run_01JB9'
const PLAN: PlanBlock[] = useCase.plan.map((block) => ({ key: block.key, name: block.name, kind: block.kind as BlockKind }))
const COORDINATOR = { kind: 'agent', id: 'coordinator', display: 'AI troubleshooter' }
const ALICE = { kind: 'user', id: 'alice', display: 'Alice' }
const nameOf = (id: string) => (id === 'alice' ? 'Alice' : id)

let seq = failure.length
let handoffs = 0

function wire(kind: string, summary: string, data: Record<string, unknown>, actor: object = COORDINATOR) {
  seq += 1
  return { run_id: RUN, seq, ts: '2026-11-04T02:20:00Z', actor, summary, kind, data }
}

const FIX = 'fix_01FIRST'
const ASKED_AT = Date.parse('2026-11-04T02:20:00Z')
const ENDS_BY = ASKED_AT + 20 * 60_000
const BEFORE = ENDS_BY - 1
const started = () => wire('fix_started', 'Alice asked for a fix.', { fix_id: FIX, asked_by: 'alice', asked_by_name: 'Alice', ends_by: new Date(ENDS_BY).toISOString() })
/** Hand-offs are numbered within the fix, at most 12, as the contract says. */
const handoff = (to: string, found: string, summary: string, more: object = {}) => {
  handoffs += 1
  return wire('fix_handoff', summary, { fix_id: FIX, handoff: handoffs, to, blocks: [], found, widened_by: null, passed: null, scenarios: null, ...more })
}

function stopped(): RunModel {
  seq = failure.length
  handoffs = 0
  return foldWire(emptyModel, failure, RUN)
}

function withFix(...events: object[]): RunModel {
  return foldWire(stopped(), events, RUN)
}

const STATUS = 'Drafting a fix.'
const text = (html: string) => html.replace(/<[^>]*>/g, ' ').replaceAll('&#x27;', "'").replace(/\s+/g, ' ').trim()

describe('a fix on a stopped run', () => {
  const before = stopped()
  const model = withFix(
    started(),
    handoff('troubleshooter', 'confirmed', 'I found the cause in the “Read releases” block, and the platform checked the run stopped there.', { blocks: ['Read releases'] }),
    handoff('scenario_writer', 'kept', 'I asked the Scenario writer for scenarios, and the platform checked they fit this workflow.'),
    handoff('fix_drafter', 'inside', 'I asked the Fix drafter to change only the “Read releases” block. The platform checked the change stays inside the failed part.', { blocks: ['Read releases'] }),
    handoff('simulation', 'ran', 'I ran 3 scenarios in the simulation, and 2 passed.', { passed: 2, scenarios: 3 }),
    handoff('fix_drafter', 'inside', 'I asked the Fix drafter to change only the “Read releases” block. The platform checked the change stays inside the failed part.', { blocks: ['Read releases'] }),
    handoff('checker', 'passed', 'The platform checked the fixed version, and it passed.'),
  )

  it('leaves the run as it was: still stopped, at the same step, with the same line', () => {
    expect(model.phase).toEqual(before.phase)
    expect(model.failedAt).toEqual(before.failedAt)
    expect(model.agents).toEqual(before.agents)
    expect(stationsOf(model, PLAN, 'Started by Alice')).toEqual(stationsOf(before, PLAN, 'Started by Alice'))
  })

  it('brings in each sub-agent once, in the order of its first hand-off', () => {
    expect(model.fix?.agents.map((brought) => brought.agent)).toEqual([
      { id: 'scenario_writer', display: 'Scenario writer' },
      { id: 'fix_drafter', display: 'Fix drafter' },
    ])
    expect(model.fix?.ended).toBeNull()
  })

  it('says each hand-off in the log, in the words the platform wrote, from the AI troubleshooter', () => {
    const rows = logRowsOf(model.chat, nameOf, []).slice(-7)
    expect(rows.map((row) => [row.agent?.display ?? null, row.text])).toEqual([
      [null, 'Alice asked for a fix.'],
      ['AI troubleshooter', 'I found the cause in the “Read releases” block, and the platform checked the run stopped there.'],
      ['AI troubleshooter', 'I asked the Scenario writer for scenarios, and the platform checked they fit this workflow.'],
      ['AI troubleshooter', 'I asked the Fix drafter to change only the “Read releases” block. The platform checked the change stays inside the failed part.'],
      ['AI troubleshooter', 'I ran 3 scenarios in the simulation, and 2 passed.'],
      ['AI troubleshooter', 'I asked the Fix drafter to change only the “Read releases” block. The platform checked the change stays inside the failed part.'],
      ['AI troubleshooter', 'The platform checked the fixed version, and it passed.'],
    ])
    expect(rows.every((row) => row.tone === 'plain')).toBe(true)
  })

  it('announces the newest hand-off as the AI troubleshooter', () => {
    const newest = model.chat.at(-1)
    if (!newest) throw new Error('no chat')
    expect(lineOf(newest, nameOf, null)).toMatchObject({ speaker: { kind: 'agent', agent: { id: 'coordinator' } }, text: 'The platform checked the fixed version, and it passed.' })
  })

  it('shows the AI troubleshooter at work, and each sub-agent it brought in by name, with no button', () => {
    expect(troubleFaceOf('failed', model.fix, BEFORE)).toBe('working')
    const html = renderToStaticMarkup(<FixCrew fix={model.fix!} now={BEFORE} loadedUpTo={0} />)
    expect(text(html)).toBe(`${STATUS} Scenario writer Fix drafter`)
    expect(html).not.toContain('<button')
    expect(html.match(/data-face="orb"/g)).toHaveLength(2)
  })

  it('rises in only a sub-agent that arrived after the page loaded', () => {
    const scenarioWriterSeq = model.fix!.agents[0]!.seq
    const html = renderToStaticMarkup(<FixCrew fix={model.fix!} now={BEFORE} loadedUpTo={scenarioWriterSeq} />)
    expect(html.match(/data-arrived/g)).toHaveLength(1)
  })
})

describe('how a fix ends', () => {
  it('counts a fix as handed back once its twenty minutes are up, with no event to say so', () => {
    const model = withFix(started(), handoff('fix_drafter', 'inside', 'I asked the Fix drafter to change only the “Read releases” block. The platform checked the change stays inside the failed part.', { blocks: ['Read releases'] }))
    expect(model.fix?.endsBy).toBe(ENDS_BY)
    expect(model.fix?.ended).toBeNull()
    expect(troubleFaceOf('failed', model.fix, BEFORE)).toBe('working')
    expect(text(renderToStaticMarkup(<FixCrew fix={model.fix!} now={BEFORE} loadedUpTo={0} />))).toBe(`${STATUS} Fix drafter`)
    expect(troubleFaceOf('failed', model.fix, ENDS_BY)).toBe('idle')
    expect(text(renderToStaticMarkup(<FixCrew fix={model.fix!} now={ENDS_BY} loadedUpTo={0} />))).toBe("I couldn't fix this. Fix drafter")
  })

  it('says a ready fix waits for an Approver, and the faces are pleased', () => {
    const model = withFix(started(), wire('fix_round', 'Round 1: 3 of 3 scenarios passed.', { fix_id: FIX, round: 1, passed: 3, scenarios: 3, progress: true }), wire('fix_proposed', 'A fix is ready as version 4. Nothing changes until an Approver approves.', { fix_id: FIX, version: 4, digest: `sha256:${'ab'.repeat(32)}` }))
    expect(model.fix?.ended).toBe('proposed')
    expect(model.phase.state).toBe('failed')
    expect(troubleFaceOf('failed', model.fix, BEFORE)).toBe('success')
    expect(text(renderToStaticMarkup(<FixCrew fix={model.fix!} now={BEFORE} loadedUpTo={0} />))).toBe('A fix is ready. Nothing changes until an Approver approves.')
    expect(logRowsOf(model.chat, nameOf, []).at(-1)?.tone).toBe('wait')
  })

  it('says it couldn’t fix this when it hands back, and marks the row', () => {
    const model = withFix(started(), wire('fix_handed_back', "I couldn't fix this. A round made no progress. Nothing was changed.", { fix_id: FIX, why: 'no_progress' }))
    expect(model.fix?.ended).toBe('handed_back')
    expect(troubleFaceOf('failed', model.fix, BEFORE)).toBe('idle')
    expect(text(renderToStaticMarkup(<FixCrew fix={model.fix!} now={BEFORE} loadedUpTo={0} />))).toBe("I couldn't fix this.")
    expect(logRowsOf(model.chat, nameOf, []).at(-1)).toMatchObject({ tone: 'bad', text: "I couldn't fix this. A round made no progress. Nothing was changed." })
  })

  it('marks a cause named outside the version or where the run didn’t stop as refused, with no made-up name', () => {
    const model = withFix(
      started(),
      handoff('troubleshooter', 'not_in_version', "I named a block that isn't in this workflow, so the platform didn't use it."),
      handoff('troubleshooter', 'not_where_it_stopped', "I named the “Make ticket” block, but the run didn't stop there.", { blocks: ['Make ticket'] }),
    )
    expect(logRowsOf(model.chat, nameOf, []).slice(-2).map((row) => row.tone)).toEqual(['bad', 'bad'])
  })

  it('marks a cause too wide for one fix as refused', () => {
    const model = withFix(started(), handoff('troubleshooter', 'too_wide', "I named more than 10 blocks, too many for one fix, so the platform didn't use them."))
    expect(logRowsOf(model.chat, nameOf, []).at(-1)?.tone).toBe('bad')
  })

  it('marks a hand-off the platform refused', () => {
    const model = withFix(started(), handoff('fix_drafter', 'widened', 'I asked the Fix drafter to change only the “Read releases” block, but its change removes an Ask for a yes, so the platform refused it.', { blocks: ['Read releases'], widened_by: 'removes_a_yes' }))
    expect(logRowsOf(model.chat, nameOf, []).at(-1)?.tone).toBe('bad')
  })

  it('is forgotten when the run is retried', () => {
    const model = withFix(started(), wire('run_retried', 'Retried.', { leg: 'work', attempt: 2 }, ALICE))
    expect(model.fix).toBeNull()
    expect(troubleFaceOf('pending', model.fix, BEFORE)).toBe('working')
  })

  it('has no fix before anyone asks', () => {
    expect(stopped().fix).toBeNull()
    expect(troubleFaceOf('failed', null, BEFORE)).toBe('idle')
  })
})

describe('what a hand-back and the later steps keep', () => {
  const round = (n: number, passed: number, summary: string) => wire('fix_round', summary, { fix_id: FIX, round: n, passed, scenarios: 3, progress: n === 1 })

  it('keeps each round’s sentence and the hand-back’s reason code, for the card', () => {
    const model = withFix(
      started(),
      round(1, 0, 'Round 1: 0 of 3 scenarios passed.'),
      round(2, 0, 'Round 2: 0 of 3 scenarios passed, no better than before.'),
      wire('fix_handed_back', "I couldn't fix this. A round made no progress. Nothing was changed.", { fix_id: FIX, why: 'no_progress' }),
    )
    expect(model.fix?.rounds).toEqual(['Round 1: 0 of 3 scenarios passed.', 'Round 2: 0 of 3 scenarios passed, no better than before.'])
    expect(model.fix?.why).toBe('no_progress')
  })

  it('puts the Approver’s yes and no in the log, a no marked as a stop', () => {
    const BOB = { kind: 'user', id: 'bob', display: 'Bob' }
    const decided = (verdict: string, summary: string) => wire('fix_decided', summary, { fix_id: FIX, approval_id: 'apr_01A', verdict, by: 'bob', by_name: 'Bob', reason: null }, BOB)
    const yes = withFix(started(), decided('approved', 'Bob said yes to the fix.'))
    expect(logRowsOf(yes.chat, nameOf, []).at(-1)).toMatchObject({ tone: 'plain', text: 'Bob said yes to the fix.' })
    const no = withFix(started(), decided('declined', 'Bob said no to the fix. The workflow stays as it was.'))
    expect(logRowsOf(no.chat, nameOf, []).at(-1)).toMatchObject({ tone: 'bad', text: 'Bob said no to the fix. The workflow stays as it was.' })
  })

  it('puts the test run’s result in the log, a failed one marked as a stop, and never moves the run', () => {
    const tried = (result: string, summary: string) =>
      wire('fix_tried', summary, { fix_id: FIX, approval_id: 'apr_01A', approved_by: 'bob', approved_by_name: 'Bob', pressed_by: 'alice', result, test_run_id: null }, ALICE)
    const on = withFix(started(), tried('turned_on', 'The fix passed its test run, so the workflow is back on with it. Bob said yes to it.'))
    expect(logRowsOf(on.chat, nameOf, []).at(-1)?.tone).toBe('plain')
    const failed = withFix(started(), tried('test_failed', 'The fix’s test run didn’t pass, so the workflow stays as it was. Bob said yes to it.'))
    expect(logRowsOf(failed.chat, nameOf, []).at(-1)?.tone).toBe('bad')
    expect(failed.phase).toEqual(stopped().phase)
  })
})
