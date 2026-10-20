import type { DoorBox, RoomLayout } from '../run'
import { cx } from '../ui/cx'
import styles from './Room.module.css'

interface FloorPlanProps {
  layout: RoomLayout
  /** The write door swinging open while a write goes through it. */
  openDoor: string | null
  /** Doors in the order they appear during the opening, left to right. */
  order: readonly DoorBox[]
}

const GRID = 32

function Opening({ door, layout, open, index }: { door: DoorBox; layout: RoomLayout; open: boolean; index: number }) {
  const { wall, floor } = layout
  const o = door.opening
  const style = { '--i': index } as React.CSSProperties
  if (door.side === 'teams') {
    const hingeX = o.x + o.w
    const hingeY = floor.y + floor.h
    return (
      <g className={styles['opening']} style={style}>
        <rect x={o.x} y={hingeY - 1} width={o.w} height={wall + 2} className={styles['gap']} />
        <line x1={o.x} y1={hingeY - 1} x2={o.x} y2={hingeY + wall + 1} className={styles['jamb']} />
        <line x1={hingeX} y1={hingeY - 1} x2={hingeX} y2={hingeY + wall + 1} className={styles['jamb']} />
        <line x1={hingeX} y1={hingeY} x2={hingeX} y2={hingeY - o.w} className={styles['leaf']} />
        <path d={`M${hingeX} ${hingeY - o.w}A${o.w} ${o.w} 0 0 0 ${o.x} ${hingeY}`} className={styles['swing']} />
      </g>
    )
  }
  const left = door.side === 'read'
  const wallX = left ? floor.x : floor.x + floor.w
  const gapX = left ? wallX - wall - 1 : wallX - 1
  const hingeY = o.y
  const length = o.h
  const leafEndX = left ? wallX + length : wallX - length
  if (left) {
    return (
      <g className={styles['opening']} style={style}>
        <rect x={gapX} y={o.y} width={wall + 2} height={o.h} className={styles['gap']} />
        <line x1={gapX} y1={o.y} x2={wallX + 1} y2={o.y} className={styles['jamb']} />
        <line x1={gapX} y1={o.y + o.h} x2={wallX + 1} y2={o.y + o.h} className={styles['jamb']} />
        <line x1={wallX} y1={hingeY} x2={leafEndX} y2={hingeY} className={styles['leaf']} />
        <path d={`M${leafEndX} ${hingeY}A${length} ${length} 0 0 1 ${wallX} ${hingeY + length}`} className={styles['swing']} />
      </g>
    )
  }
  return (
    <g className={styles['opening']} style={style}>
      <rect x={gapX} y={o.y} width={wall + 2} height={o.h} className={styles['gap']} />
      <line x1={wallX - 1} y1={o.y} x2={gapX + wall + 2} y2={o.y} className={styles['jamb']} />
      <line x1={wallX - 1} y1={o.y + o.h} x2={gapX + wall + 2} y2={o.y + o.h} className={styles['jamb']} />
      <path
        d={`M${leafEndX} ${hingeY}A${length} ${length} 0 0 0 ${wallX} ${hingeY + length}`}
        className={cx(styles['swing'], styles['swingWrite'], open && styles['swingOpen'])}
      />
      <line
        x1={wallX}
        y1={hingeY}
        x2={wallX}
        y2={hingeY + length}
        className={cx(styles['leafClosed'], open && styles['leafOpen'])}
        style={{ transformOrigin: `${wallX}px ${hingeY}px` }}
      />
    </g>
  )
}

export function FloorPlan({ layout, openDoor, order }: FloorPlanProps) {
  const { width, height, floor, table, wall } = layout
  const inner = 10
  // A rounded rectangle, not a pill, so the ticket's corners sit inside the table.
  const tableRadius = Math.min(table.h / 2, 28)
  return (
    <svg className={styles['plan']} width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden="true" focusable="false">
      <defs>
        <pattern id="room-grid" width={GRID} height={GRID} patternUnits="userSpaceOnUse" x={floor.x} y={floor.y}>
          <path d={`M${GRID} 0H0V${GRID}`} fill="none" className={styles['gridLine']} />
        </pattern>
        <pattern id="room-hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <line x1="0" y1="0" x2="0" y2="6" className={styles['hatchLine']} />
        </pattern>
      </defs>
      <g className={styles['shell']}>
        <rect x={0} y={0} width={width} height={height} rx={18} className={styles['wallBand']} />
        <rect x={floor.x} y={floor.y} width={floor.w} height={floor.h} rx={6} className={styles['floor']} />
        <rect x={floor.x} y={floor.y} width={floor.w} height={floor.h} rx={6} fill="url(#room-grid)" />
        <rect x={0.75} y={0.75} width={width - 1.5} height={height - 1.5} rx={18} className={styles['wallEdge']} />
        <rect x={floor.x} y={floor.y} width={floor.w} height={floor.h} rx={6} className={styles['wallEdge']} />
        <rect x={table.x} y={table.y} width={table.w} height={table.h} rx={tableRadius} className={styles['table']} />
        <rect
          x={table.x + inner}
          y={table.y + inner}
          width={table.w - 2 * inner}
          height={table.h - 2 * inner}
          rx={Math.max(0, tableRadius - inner)}
          className={styles['tableInner']}
        />
      </g>
      {layout.doors.map((door) => (
        <Opening
          key={`${door.side}:${door.key ?? door.label ?? ''}:${door.box.y}`}
          door={door}
          layout={layout}
          open={door.key !== null && door.key === openDoor}
          index={order.indexOf(door)}
        />
      ))}
      <rect x={0} y={0} width={width} height={wall} fill="none" />
    </svg>
  )
}
