import aliceHome from '@contracts/fixtures/builder/home.alice.json'
import bobHome from '@contracts/fixtures/builder/home.bob.json'
import { describe, expect, it } from 'vitest'
import type { HomeOut } from '../../api/types'
import { needsOf, type Need } from '../home/home'
import { needRow } from './needs'

const NOW = new Date('2026-11-04T15:00:00+08:00')
const alice = aliceHome as HomeOut
const bob = bobHome as HomeOut
const find = (home: HomeOut, kind: Need['kind']): Need => {
  const need = needsOf(home).shown.find((item) => item.kind === kind)
  if (!need) throw new Error(`no ${kind} need in the fixture`)
  return need
}

describe('a Needs you row, as the sketch words it', () => {
  it('says what stopped and when, with the workflow first', () => {
    const row = needRow(find(alice, 'stopped'), NOW)
    expect(row.subject).toBe('Software watchlist')
    expect(row.rest).toMatch(/^stopped (at \d+:\d\d|\w{3} \d+ \w{3} at \d+:\d\d)$/)
    expect(row.tone).toBe('err')
    expect(row.group).toBe('now')
  })

  it('says what waits for a yes, in amber', () => {
    const row = needRow(find(bob, 'approval'), NOW)
    expect(row.rest).toBe('needs your yes')
    expect(row.tone).toBe('wait')
    expect(row.to).toMatch(/^\/runs\//)
  })

  it('says software GitHub can’t find, and opens its own page', () => {
    const need = find(alice, 'address')
    const row = needRow({ ...need, item: { ...need.item, moved_to: null, not_found: true } } as Need, NOW)
    expect(row.rest).toBe('can’t be found on GitHub')
    expect(row.to).toBe(`/software/${(need as Extract<Need, { kind: 'address' }>).item.software_id}`)
    expect(row.group).toBe('set')
  })

  it('says software that moved on GitHub', () => {
    const need = find(alice, 'address')
    const row = needRow({ ...need, item: { ...need.item, moved_to: 'owner/new', not_found: false } } as Need, NOW)
    expect(row.rest).toBe('moved on GitHub')
  })

  it('has no full stop and no second sentence, because a row is one line', () => {
    for (const home of [alice, bob]) {
      for (const need of needsOf(home).shown) {
        const row = needRow(need, NOW)
        expect(`${row.subject ?? ''} ${row.rest}`, need.key).not.toMatch(/\.\s|\.$/)
      }
    }
  })
})
