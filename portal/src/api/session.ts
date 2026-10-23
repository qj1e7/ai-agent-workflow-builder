import { useSyncExternalStore } from 'react'

export const DEFAULT_DEV_USER = 'alice'
const STORAGE_KEY = 'portal.dev-user'

function readStored(): string {
  try {
    return window.localStorage.getItem(STORAGE_KEY) || DEFAULT_DEV_USER
  } catch {
    return DEFAULT_DEV_USER
  }
}

let current = readStored()
const listeners = new Set<() => void>()

export function getDevUser(): string {
  return current
}

export function setDevUser(id: string): void {
  if (id === current) return
  current = id
  try {
    window.localStorage.setItem(STORAGE_KEY, id)
  } catch {
    // The choice still holds for this tab when storage is blocked.
  }
  for (const listener of listeners) listener()
}

export function subscribeDevUser(listener: () => void): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

export function useDevUser(): string {
  return useSyncExternalStore(subscribeDevUser, getDevUser, getDevUser)
}
