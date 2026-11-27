import { useEffect, useState, type CSSProperties } from 'react'
import { AgentFace } from '../../ui/AgentFace'
import { cx } from '../../ui/cx'
import { IconCheck, IconGate, IconX } from '../../ui/icons'
import { usePauseUnseen } from '../../ui/loops'
import { motionAllowed } from '../../ui/motion'
import { STEP_ICON } from '../../ui/StepLine'
import { RunLine, UnderStep } from './RunLine'
import type { StepState } from '../../ui/StepLine'
import type { Station } from './runModel'
import { geometryOf, handoffsOf, LINK_INTO, STAGE_STATE_WORDS, stageOf, type Handoff, type StageModel, type StageNode } from './stage'
import styles from './RunStage.module.css'

/** Until the stage is measured, and where nothing can be: a width a normal window gives it. */
const FIRST_WIDTH = 900

function useWidth() {
  const [node, setNode] = useState<HTMLDivElement | null>(null)
  const [width, setWidth] = useState(FIRST_WIDTH)
  useEffect(() => {
    if (!node) return undefined
    const measure = () => setWidth(node.clientWidth || FIRST_WIDTH)
    measure()
    if (typeof ResizeObserver !== 'function') return undefined
    const watch = new ResizeObserver(measure)
    watch.observe(node)
    return () => watch.disconnect()
  }, [node])
  return [width, setNode] as const
}

/** What the stage last drew, so a step reached since glows and the rest holds still. */
interface Seen {
  readonly sig: string
  readonly states: Readonly<Record<string, StepState>>
  readonly opening: boolean
  readonly plays: readonly Handoff[]
  readonly changed: ReadonlySet<string>
}

const statesOf = (stations: readonly Station[]): Record<string, StepState> => Object.fromEntries(stations.map((station) => [station.key, station.state]))
const sigOf = (stations: readonly Station[]): string => stations.map((station) => `${station.key}:${station.state}`).join('|')

function seenOf(stations: readonly Station[], stage: StageModel | null, before: Seen | null): Seen {
  const states = statesOf(stations)
  const plays = stage ? handoffsOf(stage, before ? before.states : null) : []
  const changed = new Set(before ? stations.filter((station) => before.states[station.key] !== station.state).map((station) => station.key) : [])
  return { sig: sigOf(stations), states, opening: before === null, plays, changed }
}

function Badge({ state }: { state: StepState }) {
  if (state === 'done') return <IconCheck />
  if (state === 'err') return <IconX />
  if (state === 'wait') return <IconGate />
  return null
}

function Node({ node, size, index, opening, flash, ring }: { node: StageNode; size: number; index: number; opening: boolean; flash: boolean; ring: boolean }) {
  const Picture = STEP_ICON[node.icon]
  const mark = node.state === 'done' || node.state === 'err' || node.state === 'wait'
  return (
    <li
      className={cx(styles['st'], styles[node.state], node.gate && styles['gate'])}
      data-state={node.state}
      aria-current={node.state === 'now' || node.state === 'wait' ? 'step' : undefined}
      data-play={opening || undefined}
      data-flash={flash || undefined}
      style={{ '--dl': `${(index * 0.9).toFixed(1)}s` } as CSSProperties}
    >
      <span className={styles['node']} data-ring={(ring && node.state === 'wait') || undefined}>
        {node.picture === 'face' && node.agent ? <AgentFace id={node.agent.id} display={node.agent.display} size={size} state={node.face} /> : <Picture />}
        {mark && node.picture !== 'face' ? (
          <span className={styles['badge']}>
            <Badge state={node.state} />
          </span>
        ) : null}
      </span>
      {/* Done and not reached say it by the tick and the dashed circle, so the word is for a screen reader. A timer already says the step is at work. The word comes first for a screen reader, as the step line has it, and sits under the name on screen. */}
      {node.under?.kind === 'timer' ? null : <span className={cx(styles['word'], (node.state === 'done' || node.state === 'todo') && 'visually-hidden')}>{STAGE_STATE_WORDS[node.state]}</span>}
      <span className={styles['name']}>{node.label}</span>
      {node.under ? (
        <span className={styles['under']}>
          <UnderStep under={node.under} small={false} />
        </span>
      ) : null}
    </li>
  )
}

interface RunStageProps {
  readonly stations: readonly Station[]
  /** The step the run reached while the page watched. The plain step line, when the stage falls back to it, lands it. */
  readonly arrivedLive: string | null
}

/**
 * The live activity view as a light stage (ADR 0052): the Planner above one line of up to six steps, the agents' faces on their steps,
 * a glow on each hand-off, and the approval gate in amber while it waits. A step with no agent shows its icon. A longer line falls back
 * to the plain step line. Every part comes from the run line, which comes from the run's events. It plays once when it opens, in about
 * five seconds, and after that only what changed moves. With reduced motion nothing moves and the same words and shapes say the same.
 */
export function RunStage({ stations, arrivedLive }: RunStageProps) {
  const stage = stageOf(stations)
  const sig = sigOf(stations)
  const [seen, setSeen] = useState<Seen>(() => seenOf(stations, stage, null))
  if (seen.sig !== sig) setSeen(seenOf(stations, stage, seen))
  const [width, measure] = useWidth()
  const pauseUnseen = usePauseUnseen()
  const moving = motionAllowed()
  if (!stage) return <RunLine stations={stations} arrivedLive={arrivedLive} settled={null} />
  const geometry = geometryOf(stage.nodes.length, width)
  const wireId = (id: string) => `${seen.sig}:${id}`
  return (
    <div className={styles['wrap']} ref={pauseUnseen}>
      <div
        className={styles['stage']}
        ref={measure}
        style={{ '--hub': `${geometry.hubHeight}px`, '--rise': `${geometry.rise}px`, '--node': `${geometry.node}px`, '--n': stage.nodes.length } as CSSProperties}
        data-stage
        data-opening={(moving && seen.opening) || undefined}
      >
        <svg className={styles['wires']} width={width} height={geometry.height} aria-hidden="true" focusable="false">
          {stage.wires.map((wire) =>
            wire.from === 'planner' ? (
              <path key={wire.id} className={cx(styles['wire'], styles[wire.kind])} data-hand={wire.kind} d={geometry.plan(wire.to)} />
            ) : (
              <path key={wire.id} className={styles['wire']} data-link={LINK_INTO[stage.nodes[wire.to]?.state ?? 'todo']} d={geometry.track(wire.to)} />
            ),
          )}
          {moving
            ? seen.plays.map((play) => {
                const wire = stage.wires.find((candidate) => candidate.id === play.id)
                if (!wire) return null
                return (
                  <path
                    key={wireId(play.id)}
                    className={cx(styles['pk'], styles[`pk-${wire.kind}`])}
                    data-glow={play.id}
                    pathLength={100}
                    d={wire.from === 'planner' ? geometry.plan(wire.to) : geometry.track(wire.to)}
                    style={{ '--dl': `${play.delay}s` } as CSSProperties}
                  />
                )
              })
            : null}
        </svg>
        <div className={styles['hub']}>
          <AgentFace id="planner" display="Planner" size={84} state={stage.planner} />
          <p className={styles['hubWho']}>Planner</p>
        </div>
        <ol className={styles['steps']} aria-label="Steps of this run">
          {stage.nodes.map((node, index) => (
            <Node key={node.key} node={node} size={geometry.node} index={index} opening={moving && seen.opening} flash={moving && seen.changed.has(node.key)} ring={moving} />
          ))}
        </ol>
      </div>
    </div>
  )
}
