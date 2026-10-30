import { isValidElement, type ReactElement, type ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'
import bobHome from '../../../../contracts/fixtures/builder/home.bob.json'
import type { HomeOut } from '../../api/types'
import { PageHead } from '../../shell/PageHead'
import { HomePage } from './HomePage'

const query = vi.hoisted((): { result: object } => ({ result: {} }))
vi.mock('../../api/homeQueries', () => ({ useHome: () => query.result }))

const BOB_HOME = bobHome as HomeOut
const refetch = () => Promise.resolve()
const STATES: Record<string, object> = {
  loading: { data: undefined, isError: false, refetch },
  'could not load': { data: undefined, isError: true, refetch },
  loaded: { data: BOB_HOME, isError: false, refetch },
  'could not refresh': { data: BOB_HOME, isError: true, refetch },
}

function pageIn(state: object): ReactElement<{ children: ReactNode[] }> {
  query.result = state
  return HomePage({ heading: 'Good afternoon, Bob', today: 'Tuesday 3 November.', now: new Date('2026-11-03T15:00:00+08:00') }) as ReactElement<{ children: ReactNode[] }>
}

describe('Home’s heading', () => {
  it('stays the same element, in the same place, while Home loads, fails, has loaded or cannot refresh, so the shell’s focus stays on it', () => {
    const pages = Object.entries(STATES).map(([name, state]) => [name, pageIn(state)] as const)
    const [, first] = pages[0]!
    for (const [name, page] of pages) {
      expect(page.type, name).toBe(first.type)
      const [head] = page.props.children
      expect(isValidElement(head) && head.type, name).toBe(PageHead)
      expect(isValidElement<{ heading: string }>(head) && head.props.heading, name).toBe('Good afternoon, Bob')
    }
  })
})
