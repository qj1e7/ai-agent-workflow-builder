import type { ReactElement, ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { StartDrafting } from '../../api/draftedQueries'
import type { Outcome } from '../../api/latch'
import type { DraftedWorkflowView } from '../../api/types'
import { testHooks } from '../../ui/testHooks'
import { AnyBlockLink } from './AnyBlockLink'
import { ANY_BLOCK } from './drafted'

vi.mock('react', async (importOriginal) => (await import('../../ui/testHooks')).withTestHooks(await importOriginal<object>()))

const world = vi.hoisted(() => ({
  asker: 'operator' as 'operator' | 'approver',
  sent: [] as { vars: StartDrafting; outcome: Outcome<DraftedWorkflowView> }[],
  shown: [] as string[],
}))

vi.mock('../../api/draftedQueries', () => ({
  useStartDrafting: () => ({ isPending: false, mutate: (vars: StartDrafting, outcome: Outcome<DraftedWorkflowView>) => world.sent.push({ vars, outcome }) }),
}))
vi.mock('../home/asker', () => ({ useAsker: () => world.asker }))
vi.mock('../home/ChatProvider', () => ({ useShowDraft: () => (draftedId: string) => world.shown.push(draftedId) }))
vi.mock('../../api/context', () => ({ useErrorWords: () => () => 'I couldn’t reach the platform.' }))

type Drawn = ReactElement<{ children: ReactNode[] }>
type Pressable = ReactElement<{ onClick: () => void; children: ReactNode }>

const WORDS = 'Every Monday,  email the release notes to the team '
const draw = (words: string | null) => testHooks.draw(() => AnyBlockLink({ words })) as Drawn | null
const linkOf = (drawn: Drawn | null) => drawn?.props.children[0] as Pressable

describe('pressing Build it with any n8n block', () => {
  beforeEach(() => {
    testHooks.reset()
    world.asker = 'operator'
    world.sent.length = 0
    world.shown.length = 0
  })

  it('sends the words unchanged, once for two quick presses, and shows the drafted card it started', () => {
    const link = linkOf(draw(WORDS))
    expect(link.props.children).toBe(ANY_BLOCK)
    link.props.onClick()
    link.props.onClick()
    expect(world.sent.map((sent) => sent.vars.words)).toEqual([WORDS])
    expect(world.sent[0]?.vars.idempotencyKey).toEqual(expect.any(String))
    world.sent[0]?.outcome.onSuccess?.({ drafted_id: 'dw_1' } as DraftedWorkflowView)
    expect(world.shown).toEqual(['dw_1'])
  })

  it('says why when the platform refuses, and draws nothing without words or for an Approver', () => {
    linkOf(draw(WORDS)).props.onClick()
    world.sent[0]?.outcome.onError?.(new Error('down'))
    expect(JSON.stringify(draw(WORDS))).toContain('I couldn’t reach the platform.')
    expect(draw(null)).toBeNull()
    world.asker = 'approver'
    expect(draw(WORDS)).toBeNull()
  })
})
