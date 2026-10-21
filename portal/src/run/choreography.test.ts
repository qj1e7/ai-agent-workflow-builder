import { describe, expect, it } from 'vitest'
import type { BlockView } from '../api/types'
import { choreograph, type Act, type BeatPlan, type TimedAct } from './choreography'
import { paced } from './director'
import { beatMsOf, isStory } from './kinds'
import { recording, slice, type RecordingName } from './recordings'
import { applyEvent, EMPTY_ROOM } from './room'
import { TEST_REGISTRY } from './testing'
import { trackOf, type Track } from './track'

/** contracts/fixtures/builder/templates.json, release_check. */
const RELEASE_CHECK: readonly BlockView[] = [
  { key: 'read_releases', name: 'Read GitHub releases', description: "The Release checker reads the repository's releases.", kind: 'agent' },
  { key: 'approval_gate', name: 'Approval gate', description: 'An Approver reviews the proposed ticket in Teams before it is written.', kind: 'approval' },
  { key: 'create_ticket', name: 'Create Jira ticket', description: 'One ticket in the chosen project listing the new releases.', kind: 'write_action' },
]

const RECORDINGS: readonly RecordingName[] = ['success', 'failure', 'rejected']

function trackAt(name: RecordingName, seq: number): Track {
  const room = slice(name, 1, seq).reduce((state, event) => applyEvent(state, event, TEST_REGISTRY), EMPTY_ROOM)
  return trackOf({ room, waiting: null, spedUp: false }, RELEASE_CHECK)
}

/** The plan for a story seq as the director plays it at a speed: from the frame before it to its own. */
function planOf(name: RecordingName, seq: number, speed: 1 | 2 = 1, entry: 'continuous' | 'cut' = 'continuous'): BeatPlan {
  const event = recording(name)[seq - 1]
  if (!event) throw new Error(`no seq ${seq} in ${name}`)
  return choreograph(trackAt(name, seq - 1), trackAt(name, seq), { key: `0:${seq}`, entry, durationMs: paced(event, speed), baseMs: beatMsOf(event) })
}

const storySeqs = (name: RecordingName) => recording(name).filter(isStory).map((event) => event.seq)
const what = (plan: BeatPlan) => plan.acts.map((timed) => timed.act.what)
const travelOf = (plan: BeatPlan) => plan.acts.find((timed) => timed.act.what === 'travel')
const stopOf = (act: Act) => ('stop' in act ? act.stop : null)

function endOf(timed: TimedAct): number {
  return timed.delayMs + timed.durationMs
}

describe('choreograph', () => {
  it.each(RECORDINGS)('%s: at 1x and 2x, acts never overlap and end inside the beat', (name) => {
    for (const speed of [1, 2] as const) {
      for (const seq of storySeqs(name)) {
        const plan = planOf(name, seq, speed)
        const event = recording(name)[seq - 1]
        let previousEnd = 0
        for (const timed of plan.acts) {
          expect(timed.durationMs, `seq ${seq} ${timed.act.what} at ${speed}x`).toBeGreaterThanOrEqual(0)
          expect(timed.delayMs, `seq ${seq} ${timed.act.what} starts after the act before it at ${speed}x`).toBeGreaterThanOrEqual(previousEnd)
          previousEnd = endOf(timed)
        }
        expect(previousEnd, `seq ${seq} ends inside the beat at ${speed}x`).toBeLessThanOrEqual(event ? paced(event, speed) : 0)
      }
    }
  })

  it('at 1x the approval beat travels for 900 ms and the proposal beat for at least 800 ms', () => {
    expect(travelOf(planOf('success', 18))?.durationMs).toBe(900)
    expect(travelOf(planOf('success', 12))?.durationMs).toBeGreaterThanOrEqual(800)
  })

  it.each(RECORDINGS)('%s: at 2x every act scales with the beat, so a beat that halves halves its acts', (name) => {
    for (const seq of storySeqs(name)) {
      const event = recording(name)[seq - 1]
      if (!event) continue
      const ratio = paced(event, 2) / paced(event, 1)
      const once = planOf(name, seq, 1)
      const twice = planOf(name, seq, 2)
      expect(what(twice), `seq ${seq}`).toEqual(what(once))
      twice.acts.forEach((timed, index) => {
        const at1x = once.acts[index]
        expect(Math.abs(timed.delayMs - (at1x?.delayMs ?? 0) * ratio), `seq ${seq} act ${index} delay`).toBeLessThanOrEqual(1)
        expect(Math.abs(timed.durationMs - (at1x?.durationMs ?? 0) * ratio), `seq ${seq} act ${index} length`).toBeLessThanOrEqual(1)
      })
    }
    expect(travelOf(planOf('success', 18, 2))?.durationMs, 'the approval beat halves at 2x').toBe(450)
  })

  it('plays nothing in a cut beat', () => {
    expect(planOf('success', 18, 1, 'cut')).toEqual({ key: '0:18', entry: 'cut', acts: [] })
  })

  it('on the proposal, the Room lead leaves the agent stop, the parcel travels to the draft, the lead arrives and the parcel turns into the draft', () => {
    const plan = planOf('success', 12)
    expect(plan.acts.map((timed) => [timed.act.what, stopOf(timed.act)])).toEqual([
      ['leave', 1],
      ['node', 1],
      ['travel', null],
      ['arrive', 2],
      ['nod', 2],
      ['node', 2],
      ['form', null],
    ])
    expect(travelOf(plan)?.act).toEqual({ what: 'travel', from: 1, to: 2, toBefore: false })
    expect(plan.acts.at(-1)?.act).toEqual({ what: 'form', to: 'draft', shake: false })
  })

  it('on the approval, Bob takes the seat and the arm lifts at the gate before the parcel travels to Jira', () => {
    const plan = planOf('success', 18)
    expect(plan.acts.map((timed) => [timed.act.what, stopOf(timed.act)])).toEqual([
      ['leave', 3],
      ['arrive', 3],
      ['nod', 3],
      ['arm', 3],
      ['node', 3],
      ['travel', null],
      ['node', 4],
    ])
    expect(plan.acts.find((timed) => timed.act.what === 'arm')?.act).toEqual({ what: 'arm', stop: 3, from: 'waiting', to: 'open' })
    expect(travelOf(plan)?.act).toEqual({ what: 'travel', from: 3, to: 4, toBefore: false })
  })

  it('on the request, the parcel travels in front of the gate, then the seat arrives and the arm goes to waiting, then the panel opens', () => {
    expect(what(planOf('success', 15))).toEqual(['node', 'travel', 'arrive', 'arm', 'node', 'panel'])
    expect(travelOf(planOf('success', 15))?.act).toEqual({ what: 'travel', from: 2, to: 3, toBefore: true })
  })

  it('on the agent failing, the line breaks and the parcel shakes into stopped; the run failing opens the trouble panel', () => {
    const failed = planOf('failure', 10)
    expect(what(failed)).toEqual(['node', 'form', 'break'])
    expect(failed.acts.find((timed) => timed.act.what === 'form')?.act).toEqual({ what: 'form', to: 'stopped', shake: true })
    expect(what(planOf('failure', 12))).toEqual(['panel'])
  })

  it('starts with one relayout when a proposal changes the write stops', () => {
    const blocks: readonly BlockView[] = [...RELEASE_CHECK.slice(0, 2), { key: 'update_page', name: 'Update Confluence page', description: '', kind: 'write_action' }]
    const fold = (seq: number) => slice('success', 1, seq).reduce((state, event) => applyEvent(state, event, TEST_REGISTRY), EMPTY_ROOM)
    const track = (seq: number) => trackOf({ room: fold(seq), waiting: null, spedUp: false }, blocks)
    const plan = choreograph(track(11), track(12), { key: '0:12', entry: 'continuous', durationMs: 1400, baseMs: 1400 })
    expect(what(plan)[0]).toBe('relayout')
    expect(what(plan).filter((kind) => kind === 'relayout')).toHaveLength(1)
  })
})
