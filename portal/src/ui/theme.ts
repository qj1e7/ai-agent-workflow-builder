import { useSyncExternalStore } from 'react'

export type Theme = 'light' | 'dark'

/** public/theme-boot.js reads the same key. theme.test.ts fails when the two differ. */
export const THEME_KEY = 'portal.theme'

const SYSTEM_DARK = '(prefers-color-scheme: dark)'

function parse(value: string | null): Theme | null {
  return value === 'light' || value === 'dark' ? value : null
}

function storedChoice(): Theme | null {
  try {
    return parse(window.localStorage.getItem(THEME_KEY))
  } catch {
    return null
  }
}

function systemTheme(): Theme {
  return window.matchMedia(SYSTEM_DARK).matches ? 'dark' : 'light'
}

const listeners = new Set<() => void>()

function show(theme: Theme): void {
  document.documentElement.dataset['theme'] = theme
  for (const listener of listeners) listener()
}

function onSystemChange(): void {
  if (storedChoice() === null) show(systemTheme())
}

function onStorage(event: StorageEvent): void {
  if (event.key === THEME_KEY || event.key === null) show(storedChoice() ?? systemTheme())
}

let systemQuery: MediaQueryList | undefined

function subscribe(listener: () => void): () => void {
  if (listeners.size === 0) {
    systemQuery = window.matchMedia(SYSTEM_DARK)
    systemQuery.addEventListener('change', onSystemChange)
    window.addEventListener('storage', onStorage)
  }
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
    if (listeners.size === 0) {
      systemQuery?.removeEventListener('change', onSystemChange)
      window.removeEventListener('storage', onStorage)
    }
  }
}

function snapshot(): Theme {
  return document.documentElement.dataset['theme'] === 'dark' ? 'dark' : 'light'
}

function setTheme(theme: Theme): void {
  try {
    window.localStorage.setItem(THEME_KEY, theme)
  } catch {
    // Storage is blocked. The page still switches, and the choice lasts until reload.
  }
  show(theme)
}

/**
 * The theme on screen, read from the data-theme attribute that public/theme-boot.js sets before first paint.
 * A stored choice wins. While nothing is stored, the theme follows the system.
 */
export function useTheme(): { readonly theme: Theme; readonly setTheme: (theme: Theme) => void } {
  const theme = useSyncExternalStore(subscribe, snapshot, () => 'light' as const)
  return { theme, setTheme }
}
