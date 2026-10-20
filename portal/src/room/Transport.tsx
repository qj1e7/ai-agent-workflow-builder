import { useRef, type ChangeEvent, type KeyboardEvent } from 'react'
import type { LiveView } from '../run'
import { cx } from '../ui/cx'
import { formatClock, formatDuration } from '../ui/format'
import { IconCheck, IconPause, IconPlay, IconReplay, IconWave } from '../ui/icons'
import { Pill } from '../ui/StatusPill'
import { useWidth } from './hooks'
import styles from './Transport.module.css'

interface TransportProps {
  view: LiveView
}

export function Transport({ view }: TransportProps) {
  const trackRef = useRef<HTMLDivElement>(null)
  const width = useWidth(trackRef)
  const { frame, transport, minutes } = view
  const track = width > 0 ? view.track(width) : null
  const shown = frame.shown
  const thumb = track ? track.xOf(shown) : 0
  const entryAt = minutes[Math.max(0, shown - 1)]
  const valueText = shown === 0 ? 'Before the run started' : entryAt ? entryAt.summary : `Event ${shown}`
  const canPlay = !transport.playing || (transport.settled && transport.atEdge)

  function seekTo(event: ChangeEvent<HTMLInputElement>) {
    if (!track) return
    transport.seek(track.cursorAt(Number(event.target.value)))
  }

  function stepWithKeys(event: KeyboardEvent<HTMLInputElement>) {
    if (!track) return
    const story = track.ticks.map((tick) => tick.seq)
    if (story.length === 0) return
    let next: number | null = null
    if (event.key === 'ArrowRight' || event.key === 'ArrowUp') next = story.find((seq) => seq > shown) ?? frame.head
    if (event.key === 'ArrowLeft' || event.key === 'ArrowDown') next = [...story].reverse().find((seq) => seq < shown) ?? 1
    if (event.key === 'Home') next = 1
    if (event.key === 'End') next = frame.head
    if (next === null) return
    event.preventDefault()
    transport.seek(next)
  }

  function playOrPause() {
    if (transport.settled && transport.atEdge) transport.restart()
    else if (transport.playing) transport.pause()
    else transport.play()
  }

  const state = transport.settled && transport.atEdge ? 'finished' : frame.label

  return (
    <div className={styles['transport']}>
      <button type="button" className={styles['control']} onClick={playOrPause} aria-label={canPlay ? (transport.settled && transport.atEdge ? 'Play again from the start' : 'Play') : 'Pause'}>
        {canPlay ? <IconPlay size={20} /> : <IconPause size={20} />}
      </button>
      <button type="button" className={styles['control']} onClick={transport.restart} aria-label="Restart from the beginning">
        <IconReplay size={20} />
      </button>
      <div ref={trackRef} className={styles['track']}>
        {track ? (
          <>
            <div className={styles['rail']} aria-hidden="true">
              <div className={styles['played']} style={{ transform: `scaleX(${width > 0 ? thumb / width : 0})` }} />
              {track.waits.map((wait, index) => {
                const centre = wait.x + wait.w / 2
                const align = centre < 70 ? styles['waitLabelStart'] : centre > width - 70 ? styles['waitLabelEnd'] : undefined
                return (
                  <div
                    key={index}
                    className={cx(styles['wait'], wait.tone === 'person' ? styles['waitPerson'] : styles['waitQuiet'], wait.live && styles['waitLive'])}
                    style={{ left: wait.x, width: wait.w }}
                  >
                    <span className={styles['waitFill']} style={{ width: wait.fill }} />
                    <span className={cx(styles['waitLabel'], align)}>{wait.live ? `Waiting ${formatDuration(wait.lasted)}` : `Waited ${formatDuration(wait.lasted)}`}</span>
                  </div>
                )
              })}
              {track.ticks.map((tick) => (
                <span key={tick.seq} className={cx(styles['tick'], tick.seq <= shown && styles['tickPast'])} style={{ left: tick.x }} />
              ))}
            </div>
            <input
              type="range"
              className={styles['range']}
              min={0}
              max={width}
              step={1}
              value={thumb}
              onChange={seekTo}
              onKeyDown={stepWithKeys}
              aria-label="Position in the run"
              aria-valuetext={valueText}
            />
          </>
        ) : null}
      </div>
      <span className={styles['elapsed']}>
        {formatClock(frame.elapsed.at)} <span className={styles['of']}>of</span> {formatClock(frame.elapsed.total)}
      </span>
      {state === 'live' ? (
        <Pill tone="working" icon={IconWave}>
          Live
        </Pill>
      ) : state === 'finished' ? (
        <Pill tone="done" icon={IconCheck}>
          Finished
        </Pill>
      ) : transport.settled ? (
        <Pill tone="neutral" icon={IconReplay}>
          Replay
        </Pill>
      ) : (
        <button type="button" className={styles['backToLive']} onClick={transport.backToLive}>
          <IconWave size={16} />
          Back to live
        </button>
      )}
    </div>
  )
}
