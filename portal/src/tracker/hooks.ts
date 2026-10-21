import { useState, useSyncExternalStore } from 'react'
import { runId, useLiveView, type LiveView, type WhenFinished } from '../run'
import { AGENTS } from './registry'

export function useLiveRun(id: string, whenFinished: WhenFinished): LiveView {
  return useLiveView(runId(id), { whenFinished, registry: AGENTS, speed: 1 })
}

const REDUCED = '(prefers-reduced-motion: reduce)'

function subscribeMotion(listener: () => void): () => void {
  const query = window.matchMedia(REDUCED)
  query.addEventListener('change', listener)
  return () => query.removeEventListener('change', listener)
}

export function useReducedMotion(): boolean {
  return useSyncExternalStore(subscribeMotion, () => window.matchMedia(REDUCED).matches, () => false)
}

const TECHNICAL_KEY = 'portal.technical-details'

function readTechnical(): boolean {
  try {
    return window.localStorage.getItem(TECHNICAL_KEY) === 'on'
  } catch {
    return false
  }
}

export function useTechnicalDetails(): [boolean, (on: boolean) => void] {
  const [on, setOn] = useState(readTechnical)
  const set = (next: boolean) => {
    setOn(next)
    try {
      window.localStorage.setItem(TECHNICAL_KEY, next ? 'on' : 'off')
    } catch {
      // The choice still holds for this page when storage is blocked.
    }
  }
  return [on, set]
}
