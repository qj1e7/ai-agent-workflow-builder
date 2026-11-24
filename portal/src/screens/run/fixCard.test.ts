import { describe, expect, it } from 'vitest'
import type { FixView } from '../../api/types'
import { askFix, fixLine, fixStageOf, handedBackWords, NO_AI_MODEL, ONLY_OPERATORS, TIME_LIMIT } from './fixCard'
import type { FixState, RunTime } from './runModel'

const ASKED = Date.parse('2026-11-04T02:20:00Z')
const ENDS = ASKED + 20 * 60_000
const BEFORE = ENDS - 1

const fix = (over: Partial<FixState> = {}): FixState => ({ id: 'fix_01FIRST', agents: [], ended: null, endsBy: ENDS as RunTime, rounds: [], back: null, ...over })
const view = (over: Partial<FixView> = {}): FixView => ({
  fix_id: 'fix_01FIRST',
  run_id: 'run_01JB9',
  use_case_id: 'uc_01JB9',
  name: 'Release check',
  state: 'waiting',
  said: 'Waiting for a yes. Nothing changes until an Approver says yes.',
  asked_by: 'alice',
  asked_by_name: 'Alice',
  ends_by: new Date(ENDS).toISOString(),
  approval_id: 'apr_01A',
  question: null,
  can_turn_back_on: false,
  ...over,
})

describe('where a fix stands', () => {
  it('has no stage before anyone asks', () => {
    expect(fixStageOf(null, undefined, BEFORE)).toBeNull()
  })

  it('reads the events until the platform answers', () => {
    expect(fixStageOf(fix(), undefined, BEFORE)).toBe('drafting')
    expect(fixStageOf(fix({ ended: 'proposed' }), undefined, BEFORE)).toBe('ready')
    expect(fixStageOf(fix({ ended: 'handed_back' }), undefined, BEFORE)).toBe('handed_back')
  })

  it('takes the platform’s state once it answers, for the same fix only', () => {
    expect(fixStageOf(fix({ ended: 'proposed' }), view({ state: 'approved' }), BEFORE)).toBe('approved')
    expect(fixStageOf(fix({ ended: 'proposed' }), view({ state: 'testing' }), BEFORE)).toBe('testing')
    expect(fixStageOf(fix({ ended: 'proposed' }), view({ fix_id: 'fix_01OTHER', state: 'on' }), BEFORE)).toBe('ready')
  })

  it('reads as ended, never as spinning, once the twenty minutes are up', () => {
    expect(fixStageOf(fix(), undefined, ENDS)).toBe('handed_back')
    expect(fixStageOf(fix(), view({ state: 'drafting' }), ENDS)).toBe('handed_back')
    expect(fixStageOf(fix({ ended: 'proposed' }), view({ state: 'waiting' }), ENDS)).toBe('ready')
  })
})

describe('the sentence under the stop', () => {
  it('is the platform’s own once it answers, and the activity’s until then', () => {
    expect(fixLine(fix(), undefined, BEFORE)).toBe('Drafting a fix.')
    expect(fixLine(fix({ ended: 'proposed' }), view(), BEFORE)).toBe('Waiting for a yes. Nothing changes until an Approver says yes.')
    expect(fixLine(fix(), view({ fix_id: 'fix_01OTHER' }), BEFORE)).toBe('Drafting a fix.')
  })

  it('says it couldn’t fix this once time is up, whatever the platform last said', () => {
    expect(fixLine(fix(), view({ state: 'drafting', said: 'Drafting a fix. Nothing changes until an Approver says yes.' }), ENDS)).toBe("I couldn't fix this.")
  })
})

describe('why a fix was handed back', () => {
  it('is the platform’s sentence without its heading and its closing line', () => {
    const back = fix({ ended: 'handed_back', back: "I couldn't fix this. A round made no progress. Nothing was changed." })
    expect(handedBackWords(back, BEFORE)).toBe('A round made no progress.')
  })

  it('is the time limit when the deadline passed and nothing said why', () => {
    expect(handedBackWords(fix(), ENDS)).toBe(TIME_LIMIT)
    expect(TIME_LIMIT).toBe('I reached the time limit for one fix.')
  })

  it('has nothing to say while the fix is still going', () => {
    expect(handedBackWords(fix(), BEFORE)).toBeNull()
  })
})

describe('who is offered the button', () => {
  const base = { operator: true, next: 'report' as const, stage: null, modelOff: false }

  it('offers it to an Operator on a stop the platform says retry won’t fix', () => {
    expect(askFix(base)).toEqual({ is: 'button' })
  })

  it('tells everyone else why not, with no button', () => {
    expect(askFix({ ...base, operator: false })).toEqual({ is: 'note', words: ONLY_OPERATORS })
    expect(ONLY_OPERATORS).toBe('An Operator can ask for a fix.')
  })

  it('says so when no AI model is connected', () => {
    expect(askFix({ ...base, modelOff: true })).toEqual({ is: 'note', words: NO_AI_MODEL })
  })

  it('offers nothing for an outage a retry fixes, or before the troubleshooter answers', () => {
    expect(askFix({ ...base, next: 'retry' })).toBeNull()
    expect(askFix({ ...base, next: undefined })).toBeNull()
  })

  it('offers nothing while a fix is under way or done, and again after one that ended without turning on', () => {
    for (const stage of ['drafting', 'ready', 'approved', 'testing', 'on'] as const) expect(askFix({ ...base, stage })).toBeNull()
    for (const stage of ['handed_back', 'declined', 'dropped', 'test_failed'] as const) expect(askFix({ ...base, stage })).toEqual({ is: 'button' })
  })
})
