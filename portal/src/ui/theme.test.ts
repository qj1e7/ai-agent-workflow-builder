/// <reference types="node" />
import { runInNewContext } from 'node:vm'
import { describe, expect, it } from 'vitest'
import indexHtml from '../../index.html?raw'
import bootScript from '../../public/theme-boot.js?raw'
import { THEME_KEY } from './theme'

interface System {
  stored: string | null
  /** Null when the browser cannot say. */
  systemDark: boolean | null
  storageBlocked?: boolean
}

function themeAfterBoot({ stored, systemDark, storageBlocked = false }: System): string | undefined {
  const dataset: Record<string, string> = {}
  const window = {
    localStorage: {
      getItem(key: string): string | null {
        if (storageBlocked) throw new Error('storage is blocked')
        return key === THEME_KEY ? stored : null
      },
    },
    matchMedia(query: string) {
      if (systemDark === null) throw new Error('no matchMedia')
      return { matches: query === '(prefers-color-scheme: dark)' && systemDark }
    },
  }
  runInNewContext(bootScript, { window, document: { documentElement: { dataset } } })
  return dataset['theme']
}

describe('public/theme-boot.js', () => {
  it.each([
    { stored: 'dark', systemDark: false, expected: 'dark' },
    { stored: 'light', systemDark: true, expected: 'light' },
    { stored: null, systemDark: true, expected: 'dark' },
    { stored: null, systemDark: false, expected: 'light' },
    { stored: 'blue', systemDark: true, expected: 'dark' },
  ] as const)('shows $expected when the stored choice is $stored and the system is dark: $systemDark', ({ expected, ...system }) => {
    expect(themeAfterBoot(system)).toBe(expected)
  })

  it('reads the key that useTheme writes, so a stored choice survives a reload', () => {
    expect(themeAfterBoot({ stored: 'dark', systemDark: false })).toBe('dark')
  })

  it('falls back to the system when storage is blocked, and to light when the system cannot say', () => {
    expect(themeAfterBoot({ stored: 'dark', systemDark: false, storageBlocked: true })).toBe('light')
    expect(themeAfterBoot({ stored: 'light', systemDark: true, storageBlocked: true })).toBe('dark')
    expect(themeAfterBoot({ stored: null, systemDark: null, storageBlocked: true })).toBe('light')
  })
})

describe('index.html', () => {
  it('runs the boot script before anything else in the head, so the first paint has a theme', () => {
    expect(indexHtml).toMatch(/<head>\s*<script src="\/theme-boot\.js"><\/script>/)
  })
})
