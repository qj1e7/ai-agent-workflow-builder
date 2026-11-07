import { isValidElement, type ReactElement, type ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'
import bobHome from '../../../../contracts/fixtures/builder/home.bob.json'
import type { HomeOut } from '../../api/types'
import { PageHead } from '../../shell/PageHead'
import { HomeBody, HomePage } from './HomePage'

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
  return HomePage({ heading: 'Good afternoon! Bob', today: 'Tuesday 3 November.', now: new Date('2026-11-03T15:00:00+08:00') }) as ReactElement<{ children: ReactNode[] }>
}

const [, slot] = [0, 1]

describe('Home’s heading', () => {
  it('is drawn once by one element, in the same place, whether or not the last refresh worked, so the shell’s focus stays on it', () => {
    const [loaded, refreshFailed] = [pageIn(STATES['loaded']!), pageIn(STATES['could not refresh']!)]
    for (const page of [loaded, refreshFailed]) {
      const body = page.props.children[slot]
      expect(isValidElement(body) && body.type).toBe(HomeBody)
      expect(isValidElement<{ heading: string }>(body) && body.props.heading).toBe('Good afternoon! Bob')
    }
  })

  it('draws no heading while Home loads, so the shell moves focus to the first one drawn', () => {
    const body = pageIn(STATES['loading']!).props.children[slot]
    expect(isValidElement(body) && body.type).not.toBe(HomeBody)
    expect(isValidElement(body) && body.type).not.toBe(PageHead)
  })

  it('keeps a heading when Home could not load, with a way to try again', () => {
    const [head] = (pageIn(STATES['could not load']!).props.children[slot] as ReactElement<{ children: ReactNode[] }>).props.children
    expect(isValidElement(head) && head.type).toBe(PageHead)
  })
})
