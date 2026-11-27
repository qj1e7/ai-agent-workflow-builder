import failure from '@contracts/fixtures/runs/failure.json'
import success from '@contracts/fixtures/runs/success.json'
import { describe, expect, it } from 'vitest'
import { historyOpen } from './historyOpen'
import { emptyModel, foldWire } from './runModel'

const replay = (raw: readonly { run_id: string; seq: number }[], upTo = Infinity) => {
  const kept = raw.filter((item) => item.seq <= upTo)
  return foldWire(emptyModel, kept, kept[0]?.run_id ?? '')
}

describe('Run history', () => {
  it('stays folded on a stopped run, where the troubleshooter already says what happened', () => {
    expect(historyOpen(null, replay(failure))).toBe(false)
  })

  it('stays folded on a finished run', () => {
    expect(historyOpen(null, replay(success))).toBe(false)
  })

  it('opens while the agents work', () => {
    expect(historyOpen(null, replay(success, 3))).toBe(true)
  })

  it('follows what the person chose', () => {
    expect(historyOpen(true, replay(failure))).toBe(true)
    expect(historyOpen(false, replay(success, 3))).toBe(false)
  })
})
