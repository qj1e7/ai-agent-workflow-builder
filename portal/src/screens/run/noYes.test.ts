import card from '@contracts/fixtures/runs/card.json'
import failure from '@contracts/fixtures/runs/failure.json'
import rejected from '@contracts/fixtures/runs/rejected.json'
import success from '@contracts/fixtures/runs/success.json'
import { describe, expect, it } from 'vitest'
import type { ApprovalStepView, Refusal } from '../../api/types'
import { leadWords, recordWords, turnWords, waitingWords } from './approvalWords'
import { standingOf, type Standing } from './decision'
import { decidesLine, statusOf, workingLine } from './happened'
import { STEP_STATE_WORDS } from '../../ui/StepLine'
import { emptyModel, foldWire, type RunModel } from './runModel'
import { stageAnswers } from './stageAnswers'
import { announcementOf, factsOf, fixWords, GATE_STEP, lineOf, lockWords, logRowsOf, runPill, stageWords, type RunState } from './words'

/**
 * The team lead's rule of 25 Nov: "yes" is never a noun. This sweeps every sentence the run page and its side panel can build,
 * in every state, so one left behind fails here and not in front of the sponsor.
 */
const YES = /\byes\b/i

const named = (id: string) => ({ alice: 'Alice', bob: 'Bob', carol: 'Carol' })[id] ?? id
const QUICK = ['Not this week', 'Wrong version']
const NOW = new Date('2026-11-03T10:00:00+08:00')

function replay(raw: readonly { run_id: string; seq: number }[], upTo = Infinity): RunModel {
  const kept = raw.filter((item) => item.seq <= upTo)
  return foldWire(emptyModel, kept, kept[0]?.run_id ?? '')
}

const STATES: readonly RunState[] = ['pending', 'working', 'proposed', 'awaiting_approval', 'acting', 'succeeded', 'rejected', 'failed', 'skipped', 'expired', 'lost']
const REFUSALS: readonly (Refusal | null)[] = [null, 'own_work', 'not_an_approver', 'not_open', 'decided_earlier_step', 'not_eligible']
const PARTIES = [
  null,
  { ownsIt: true, startedIt: true, retriedIt: false, schedule: false },
  { ownsIt: true, startedIt: false, retriedIt: false, schedule: false },
  { ownsIt: false, startedIt: false, retriedIt: true, schedule: false },
  { ownsIt: true, startedIt: true, retriedIt: false, schedule: true },
] as const

function everyRunWord(): string[] {
  const words: string[] = []
  const facts = STATES.flatMap((state) => [
    factsOf(state, { approvedBy: ['bob'], declinedBy: 'bob', refs: ['MOCK-1'], count: 1, retried: true }),
    factsOf(state, { count: 0, tickets: false }),
    factsOf(state, { outcome: 'test_passed', test: true, count: 1 }),
    factsOf(state, { whyStopped: 'GitHub did not answer.' }),
  ])
  for (const one of facts) words.push(stageWords(one, named), runPill(one).label, statusOf(one, named).label, workingLine(one))
  for (const model of [replay(success), replay(rejected), replay(failure), replay(card), replay(success, 15), replay(success, 18)]) {
    for (const item of model.chat) {
      words.push(lineOf(item, named, 'The tickets will be proposed again at the next check.').text, announcementOf(item, named, null) ?? '')
    }
    for (const row of logRowsOf(model.chat, named, QUICK)) if (row.agent === null) words.push(row.text)
    for (const answer of stageAnswers(model, '', named)) words.push(answer.label, answer.text)
  }
  const step = (status: ApprovalStepView['status'], post: ApprovalStepView['post']): ApprovalStepView => ({ index: 0, label: 'Team approver', status, decided_by: 'bob', decided_at: '2026-11-03T01:04:00Z', reason: 'Wrong version', post, sent_to: [], sent_at: '2026-11-03T01:00:00Z' })
  const standings: Standing[] = [
    standingOf([step('open', 'sent')]),
    standingOf([step('open', 'failed')]),
    standingOf([step('open', 'waiting')]),
    standingOf([step('approved', 'sent')]),
    standingOf([step('declined', 'sent')]),
    standingOf([step('expired', 'sent')]),
    standingOf([step('cancelled', 'sent')]),
    standingOf([step('closed', 'sent')]),
    standingOf([{ ...step('approved', 'sent'), index: 0 }, { ...step('open', 'sent'), index: 1, decided_by: null }]),
  ]
  for (const standing of standings) {
    for (const one of facts) words.push(recordWords(standing, one, named, QUICK, NOW) ?? '')
    words.push(turnWords(standing, named) ?? '')
  }
  for (const refusal of REFUSALS) {
    words.push(waitingWords(refusal), waitingWords(refusal, false))
    for (const party of PARTIES) {
      words.push(lockWords(refusal, party))
      for (const post of ['sent', 'failed', 'waiting'] as const) words.push(decidesLine({ steps: [step('open', post)], canDecide: false, whyNot: refusal, party, now: NOW }))
    }
  }
  for (const [requests, yours, waiting] of [[1, true, []], [2, true, []], [1, false, []], [2, false, []], [1, false, ['Bob']], [1, false, ['Bob', 'Carol']]] as const) words.push(leadWords(requests, yours, waiting))
  for (const state of ['proposed', 'handed_back', null] as const) words.push(fixWords({ ended: state, endsBy: 0 } as Parameters<typeof fixWords>[0], 0))
  words.push(...Object.values(STEP_STATE_WORDS), GATE_STEP)
  return words.filter((word) => word !== '')
}

describe('yes is never a noun on the run page or its side panel', () => {
  it('in any sentence the page builds for any state', () => {
    const words = everyRunWord()
    expect(words.length).toBeGreaterThan(300)
    expect(words.filter((word) => YES.test(word))).toEqual([])
  })
})
