import { useRef } from 'react'
import { connectorLabel } from '../api/labels'
import type { Box, Finding, Point, RoomSize } from '../run'
import { IconTag } from '../ui/icons'
import { CHIP_FRAME, CHIP_TYPE } from './chips'
import { useBeatAnimation, type AnimationPlan } from './hooks'
import { EASE_MOVE, slideOffset } from './motion'
import styles from './Finding.module.css'

export interface Land {
  readonly key: string
  readonly fromMs: number
  /** Every chip is at rest by now, so the table reads still before the beat ends. */
  readonly byMs: number
  readonly agentAt: Point
}

export interface Fold {
  readonly key: string
  readonly atMs: number
}

export const CHIP_STAGGER_MS = 60
export const CHIP_HOLD_MS = 250
export const CHIP_SLIDE_START_SHARE = 0.75
export const CHIP_FOLD_LEAD_MS = 250
const FOLD_MS = 500
const FOLD: Keyframe[] = [
  { transform: 'scale(1)', opacity: 1 },
  { transform: 'scale(0.6)', opacity: 0 },
]

interface FindingChipsProps {
  finding: Finding
  spot: Box
  size: RoomSize
  land: Land | null
  fold: Fold | null
  motion: boolean
}

export function FindingChips({ finding, spot, size, land, fold, motion }: FindingChipsProps) {
  return (
    <div className={styles['finding']} style={{ left: spot.x, top: spot.y, width: spot.w, height: spot.h, gap: CHIP_FRAME.gap }} data-finding={finding.step}>
      {finding.from ? <FromLine label={connectorLabel(finding.from)} size={size} land={land} fold={fold} motion={motion} /> : null}
      <div className={styles['chips']} style={{ gap: CHIP_FRAME.gap }}>
        {finding.items.map((item, index) => (
          <Chip key={`${index}:${item}`} item={item} index={index} spot={spot} size={size} land={land} fold={fold} motion={motion} />
        ))}
      </div>
    </div>
  )
}

interface FromLineProps {
  label: string
  size: RoomSize
  land: Land | null
  fold: Fold | null
  motion: boolean
}

function FromLine({ label, size, land, fold, motion }: FromLineProps) {
  const ref = useRef<HTMLSpanElement>(null)
  const type = CHIP_TYPE[size]
  const plan = land ? fromLandPlan(land) : fold ? fromFoldPlan(fold) : null
  useBeatAnimation(ref, land?.key ?? fold?.key ?? null, plan, motion)
  return (
    <span ref={ref} className={styles['from']} style={{ fontSize: type.from, lineHeight: `${type.fromLine}px` }}>
      From {label}
    </span>
  )
}

interface ChipProps {
  item: string
  index: number
  spot: Box
  size: RoomSize
  land: Land | null
  fold: Fold | null
  motion: boolean
}

function Chip({ item, index, spot, size, land, fold, motion }: ChipProps) {
  const ref = useRef<HTMLSpanElement>(null)
  const type = CHIP_TYPE[size]
  const plan = land ? (element: HTMLSpanElement) => landPlan(element, index, spot, land) : fold ? foldPlan(fold) : null
  useBeatAnimation(ref, land?.key ?? fold?.key ?? null, plan, motion)
  return (
    <span
      ref={ref}
      className={styles['chip']}
      style={{ padding: `${CHIP_FRAME.padY}px ${CHIP_FRAME.padX}px`, gap: CHIP_FRAME.iconGap, fontSize: type.text, lineHeight: `${type.line}px` }}
    >
      <IconTag size={CHIP_FRAME.icon} />
      {item}
    </span>
  )
}

function landPlan(element: HTMLElement, index: number, spot: Box, land: Land): AnimationPlan {
  const start = slideOffset(centreInRoom(element, spot), land.agentAt)
  const delay = land.fromMs + index * CHIP_STAGGER_MS
  return {
    keyframes: [
      { transform: `translate(${start.x}px, ${start.y}px) scale(0.96)`, opacity: 0 },
      { transform: 'translate(0px, 0px) scale(1)', opacity: 1 },
    ],
    options: { duration: Math.max(0, land.byMs - delay), delay, easing: EASE_MOVE, fill: 'both' },
  }
}

function centreInRoom(chip: HTMLElement, spot: Box): Point {
  return { x: spot.x + chip.offsetLeft + chip.offsetWidth / 2, y: spot.y + chip.offsetTop + chip.offsetHeight / 2 }
}

function foldPlan(fold: Fold): AnimationPlan {
  return { keyframes: FOLD, options: { duration: FOLD_MS, delay: fold.atMs, easing: EASE_MOVE, fill: 'both' } }
}

function fromLandPlan(land: Land): AnimationPlan {
  return {
    keyframes: [{ opacity: 0 }, { opacity: 1 }],
    options: { duration: Math.max(0, land.byMs - land.fromMs), delay: land.fromMs, easing: EASE_MOVE, fill: 'both' },
  }
}

function fromFoldPlan(fold: Fold): AnimationPlan {
  return {
    keyframes: [{ opacity: 1 }, { opacity: 0 }],
    options: { duration: FOLD_MS, delay: fold.atMs, easing: EASE_MOVE, fill: 'both' },
  }
}
