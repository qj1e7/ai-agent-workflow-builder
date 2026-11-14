import type { BuildLineView, N8nBlockKind, N8nBlockView, UseCaseState } from '../../api/types'
import type { Phase, RunModel, Station } from '../run/runModel'
import { sentence, stageFactsOf, stageWords } from '../run/words'
import { edgeKey, type EdgeState, type NodeState } from '../../ui/canvasLayout'

/** The sketch's step between two blocks of the build, which the replay keeps between two lines of the log at the least. */
export const LINE_STEP_MS = 320

/**
 * When each line of the build log shows, counted from when the platform's answer came. The lines keep their order and their real
 * gaps, and a gap shorter than `step` is drawn out to it so each line can be read. With no motion, `step` is 0 and all show at once.
 */
export function lineTimes(log: readonly BuildLineView[], from: number, step: number): number[] {
  const times: number[] = []
  log.forEach((line, index) => {
    const before = log[index - 1]
    const gap = before === undefined ? 0 : Math.max(Date.parse(line.at) - Date.parse(before.at), 0)
    const last = times[index - 1]
    times.push(last === undefined ? from : last + (step === 0 ? 0 : Math.max(gap, step)))
  })
  return times
}

export interface Replay {
  readonly lines: readonly BuildLineView[]
  readonly done: boolean
  /** When the next line is due, or null once all have shown. */
  readonly next: number | null
}

export function replayAt(log: readonly BuildLineView[], from: number, step: number, now: number): Replay {
  const times = lineTimes(log, from, step)
  const shown = times.filter((time) => time <= now).length
  return { lines: log.slice(0, shown), done: shown === log.length, next: times[shown] ?? null }
}

/**
 * Where a set-up stands: its log replays, it is saved as a draft until the platform names a test run, the test run goes, it passed
 * or stopped, and it is on once the platform says so.
 */
export type BuildStage =
  | { readonly kind: 'laying_out' }
  | { readonly kind: 'saved' }
  | { readonly kind: 'testing' }
  | { readonly kind: 'passed' }
  | { readonly kind: 'stopped' }
  | { readonly kind: 'on' }

const RUNNING: ReadonlySet<Phase['state']> = new Set(['pending', 'working', 'proposed', 'awaiting_approval', 'acting'])

/**
 * `started` is true once the platform named the test run. `test` is its phase from its own events, null before they are read. `life` is
 * the workflow as the platform holds it.
 */
export function buildStage(replayed: boolean, started: boolean, test: Phase | null, life: UseCaseState | undefined): BuildStage {
  if (life === 'on') return { kind: 'on' }
  if (!replayed) return { kind: 'laying_out' }
  if (!started) return { kind: 'saved' }
  if (test === null || RUNNING.has(test.state)) return { kind: 'testing' }
  return test.state === 'succeeded' ? { kind: 'passed' } : { kind: 'stopped' }
}

export type PillTone = 'new' | 'ok' | 'quiet'

const PILLS: Readonly<Record<BuildStage['kind'], { readonly label: string; readonly tone: PillTone }>> = {
  laying_out: { label: 'Building', tone: 'new' },
  saved: { label: 'Building', tone: 'new' },
  testing: { label: 'Building', tone: 'new' },
  passed: { label: 'Ready', tone: 'ok' },
  stopped: { label: 'Draft', tone: 'quiet' },
  on: { label: 'On', tone: 'new' },
}

export const draftPill = (stage: BuildStage): { readonly label: string; readonly tone: PillTone } => PILLS[stage.kind]

export interface Laid {
  /** True when the platform laid the workflow out in n8n, so the words may say so. */
  readonly inN8n: boolean
  readonly version: number
}

const lastStatus = (lines: readonly BuildLineView[]): string | null => lines.findLast((line) => line.kind === 'status')?.text ?? null

/** The build panel's line under its title: what the builder is doing, from its own log, then the test run, then what the platform says. */
export function statusOf(stage: BuildStage, shown: readonly BuildLineView[], laid: Laid): string {
  switch (stage.kind) {
    case 'laying_out':
      return lastStatus(shown) ?? 'Starting…'
    case 'testing':
      return 'Test run…'
    case 'saved':
    case 'passed':
    case 'stopped':
      return lastStatus(shown) ?? 'Saved as a draft.'
    case 'on':
      return laid.inN8n ? `On. Version ${String(laid.version)}, published in n8n.` : `On. Version ${String(laid.version)}.`
  }
}

export interface Check {
  readonly ok: boolean
  readonly text: string
}

/** How the test run went, in the run's own stage words, once it ended. A test run never writes, and its words say so. */
export function testStatus(model: RunModel): Check | null {
  if (RUNNING.has(model.phase.state)) return null
  const words = stageWords({ ...stageFactsOf(model), test: true }, (id) => model.people[id] ?? id)
  return model.phase.state === 'succeeded' ? { ok: true, text: words } : { ok: false, text: `The test run stopped. ${sentence(words)}` }
}

/** What the card does about the test run now: start it, wait for the log or the workflow's read, or nothing, because it was asked for or runs. */
export type TestStep = 'start' | 'wait' | 'none'

export interface TestAsk {
  readonly testRunId: string | null
  /** The key the next start asks with. Test again makes a new one. */
  readonly testKey: string
  /** The key a start was last asked with, so a card drawn again never asks twice with it. */
  readonly testAsked: string | null
}

export function testStep(ask: TestAsk | undefined, replayed: boolean, life: UseCaseState | undefined): TestStep {
  if (ask === undefined || ask.testRunId !== null || life === 'on' || life === 'paused') return 'none'
  if (!replayed || life === undefined) return 'wait'
  return ask.testAsked === ask.testKey ? 'none' : 'start'
}

/** The checks that passed so far, then how the test run went. A Tell in a test run sends nothing, and says what it would have sent. */
export function checksOf(shown: readonly BuildLineView[], test: Check | null, told: readonly string[] = []): Check[] {
  const checks = shown.filter((line) => line.kind === 'check').map((line) => ({ ok: true, text: line.text }))
  return [...checks, ...told.map((text) => ({ ok: true, text })), ...(test ? [test] : [])]
}

/** What the safety checker changed, which the card shows beside its face. */
export const notesOf = (shown: readonly BuildLineView[]): string[] => shown.filter((line) => line.kind === 'note').map((line) => line.text)

/** What the replay has shown: the blocks once the builder was adding them, and the yes once the safety checker's note says it added one. */
export interface Shown {
  readonly laid: boolean
  readonly yes: boolean
}

export function shownOf(log: readonly BuildLineView[], lines: readonly BuildLineView[], done: boolean): Shown {
  const laid = lines.length > 0 || done
  const noted = log.some((line) => line.kind === 'note')
  return { laid, yes: laid && (!noted || lines.some((line) => line.kind === 'note')) }
}

export interface CanvasState {
  readonly nodes: Readonly<Record<string, NodeState>>
  /** Keyed `{from}->{to}`, by the blocks' names. */
  readonly edges: Readonly<Record<string, EdgeState>>
}

const ENTRIES: ReadonlySet<N8nBlockKind> = new Set(['start', 'manual'])
const WORK: ReadonlySet<N8nBlockKind> = new Set(['read', 'agent', 'propose'])
const PAST_WORK: ReadonlySet<N8nBlockKind> = new Set(['branch', 'merge'])
const WORKING: ReadonlySet<Phase['state']> = new Set(['pending', 'working'])

/** Where a test run's events say it reached, block kind by block kind. A test asks nobody for a yes and writes nothing, so those blocks are never ticked by it. */
function reached(kind: N8nBlockKind, test: RunModel): NodeState | null {
  const { phase } = test
  const started = test.seq > 0
  const workDone = !WORKING.has(phase.state) && !(phase.state === 'failed' && (phase.stage === 'pending' || phase.stage === 'working'))
  if (ENTRIES.has(kind)) return started ? 'ok' : null
  if (WORK.has(kind)) return !started ? null : workDone ? 'ok' : phase.state === 'failed' ? null : 'now'
  if (PAST_WORK.has(kind)) return started && workDone && phase.state !== 'failed' ? 'ok' : null
  if (kind === 'end') return phase.state === 'succeeded' && phase.outcome === 'nothing_to_write' ? 'ok' : null
  if (kind === 'tell') return test.chat.some((item) => item.kind === 'told') ? 'ok' : null
  if (kind === 'write') return test.written.length > 0 ? 'ok' : null
  return null
}

/**
 * The canvas while it is built and tested. A block shows once the log says it was added, the yes once the safety checker's note
 * says it added one, ringed until the workflow is on. Only the test run's own events tick a block or move the dashes.
 */
export function canvasOf(blocks: readonly N8nBlockView[], log: readonly BuildLineView[], shown: Shown, test: RunModel | null, on: boolean): CanvasState {
  const noted = log.some((line) => line.kind === 'note')
  const nodes: Record<string, NodeState> = {}
  for (const block of blocks) {
    const added = block.kind === 'ask' && noted
    if (!shown.laid || (added && !shown.yes)) nodes[block.name] = 'off'
    else nodes[block.name] = (test ? reached(block.kind, test) : null) ?? (added && !on ? 'added' : 'idle')
  }
  const edges: Record<string, EdgeState> = {}
  for (const block of blocks) {
    for (const exit of block.next) {
      const from = nodes[block.name] ?? 'off'
      const to = nodes[exit.to] ?? 'off'
      edges[edgeKey(block.name, exit.to)] = from === 'off' || to === 'off' ? 'off' : from === 'ok' && to === 'ok' ? 'ok' : from === 'ok' && to === 'now' ? 'flow' : 'idle'
    }
  }
  return { nodes, edges }
}

export interface BuildLine {
  readonly stations: readonly Station[]
  /** The steps not shown yet. */
  readonly hidden: ReadonlySet<string>
  /** The step the safety checker added, ringed until the workflow is on. */
  readonly added: string | null
}

/**
 * The card's line while it builds: the workflow's steps from the schedule, hidden until the log adds them, the yes until the
 * safety checker's note. Before the test run starts nothing is ticked. Once it starts, its own events give each step's state.
 */
export function buildLine(stations: readonly Station[], log: readonly BuildLineView[], shown: Shown, tested: boolean, on: boolean): BuildLine {
  const drawn = stations.map((station, index): Station => {
    const first = index === 0 ? { icon: 'schedule' as const } : {}
    return tested ? { ...station, ...first } : { ...station, ...first, state: 'todo', face: 'idle', under: null }
  })
  const gate = stations.find((station) => station.spot.at === 'gate')?.key ?? null
  const hidden = new Set(!shown.laid ? stations.map((station) => station.key) : !shown.yes && gate !== null ? [gate] : [])
  const noted = log.some((line) => line.kind === 'note')
  return { stations: drawn, hidden, added: on || !noted ? null : gate }
}
