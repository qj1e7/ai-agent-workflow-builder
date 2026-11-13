import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import { ApiProvider } from '../../api/context'
import { createLatch } from '../../api/latch'
import { createDevSession } from '../../api/session'
import type { Me } from '../../api/types'
import { DeclinedNext, Outcome } from './Outcome'
import { pressTestAgain, testAgainOf, type TestStart } from './testAgain'

const ALICE: Me = { id: 'alice', display: 'Alice', roles: ['operator', 'approver'] }
const BOB: Me = { id: 'bob', display: 'Bob', roles: ['approver'] }
const NEXT = 'Change what it does, or run the test again.'
const DECLINED_TEST = { state: 'rejected', test: true, use_case_id: 'uc_test' } as const

const text = (html: string) => html.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim()
const buttons = (html: string) => [...html.matchAll(/<button\b[^>]*>([\s\S]*?)<\/button>/g)].map((match) => text(match[1] ?? ''))

const draw = (node: React.ReactNode) =>
  renderToStaticMarkup(
    <QueryClientProvider client={new QueryClient()}>
      <ApiProvider session={createDevSession(null)} platformFetch={fetch} origin="http://portal.test">
        <MemoryRouter>{node}</MemoryRouter>
      </ApiProvider>
    </QueryClientProvider>,
  )

describe('Do a test run again, wherever a declined test run is opened', () => {
  it('is offered to an Operator under what happens next, on the run page and in the side panel, which both draw the declined next step', () => {
    const testAgain = testAgainOf(DECLINED_TEST, ALICE, false)
    expect(testAgain).toBe('uc_test')
    const page = draw(<Outcome declinedNext={NEXT} testAgain={testAgain} />)
    const panel = draw(<DeclinedNext words={NEXT} testAgain={testAgain} />)
    for (const html of [page, panel]) {
      expect(text(html)).toContain(NEXT)
      expect(buttons(html)).toEqual(['Do a test run again'])
      const said = /<p id="([^"]+)"/.exec(html)?.[1]
      expect(html, 'the button is described by what happens next').toContain(`aria-describedby="${said ?? 'the next step'}"`)
    }
  })

  it('is offered only for a declined test run, to an Operator, while an AI model can run it', () => {
    expect(testAgainOf({ ...DECLINED_TEST, test: false }, ALICE, false), 'a declined scheduled run waits for its next run').toBeNull()
    expect(testAgainOf({ ...DECLINED_TEST, state: 'succeeded' }, ALICE, false)).toBeNull()
    expect(testAgainOf(DECLINED_TEST, BOB, false), 'only an Operator starts runs').toBeNull()
    expect(testAgainOf(DECLINED_TEST, undefined, false)).toBeNull()
    expect(testAgainOf(DECLINED_TEST, ALICE, true), 'with no AI model the test would stop at once').toBeNull()
    expect(buttons(draw(<DeclinedNext words={NEXT} testAgain={null} />))).toEqual([])
  })

  it('starts one test run of the workflow when pressed, even pressed twice in one tick, and opens it', () => {
    const started: Parameters<TestStart>[0][] = []
    const outcomes: Parameters<TestStart>[1][] = []
    const opened: string[] = []
    const latch = createLatch()
    const press = () =>
      pressTestAgain(
        latch,
        (input, outcome) => {
          started.push(input)
          outcomes.push(outcome)
        },
        { useCaseId: 'uc_test', idempotencyKey: 'key_1' },
        (runId) => opened.push(runId),
      )
    press()
    press()
    expect(started).toEqual([{ useCaseId: 'uc_test', idempotencyKey: 'key_1', test: true }])
    outcomes[0]?.onSuccess?.({ run_id: 'run_new' })
    outcomes[0]?.onSettled?.()
    expect(opened).toEqual(['run_new'])
  })
})
