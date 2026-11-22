import statuses from '@contracts/fixtures/watchlist/statuses.json'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { WatchlistView } from '../../api/types'
import { Button } from '../../ui/Button'
import { ConfirmLine } from '../../ui/ConfirmLine'
import { testHooks } from '../../ui/testHooks'
import { buttonIn, elementsOf, press, pressKey, wordsOf, type Drawn } from '../../ui/testing'
import { Schedule, TurnOffSchedule } from './Schedule'

vi.mock('react', async (importOriginal) => (await import('../../ui/testHooks')).withTestHooks(await importOriginal<object>()))
vi.mock('react-dom', async (importOriginal) => ({ ...(await importOriginal<object>()), flushSync: (update: () => void) => update() }))

interface Answers {
  readonly onSuccess?: () => void
  readonly onError?: (error: unknown) => void
  readonly onSettled?: () => void
}

/** What the schedule asked the platform for, in order, and how to answer each. */
const platform = vi.hoisted(() => ({ sent: [] as string[], answers: [] as Answers[] }))

vi.mock('../../api/queries', async (importOriginal) => {
  const mutation = (name: string) => () => ({
    isPending: false,
    isError: false,
    error: null,
    mutate: (input: unknown, answers: Answers) => {
      platform.sent.push(`${name} ${JSON.stringify(input)}`)
      platform.answers.push(answers)
    },
  })
  return { ...(await importOriginal<object>()), useTurnOffSchedule: mutation('turn off'), useSaveSchedule: mutation('save') }
})

vi.mock('../../api/workflowQueries', async (importOriginal) => ({
  ...(await importOriginal<object>()),
  useMoveWorkflow: () => ({ isPending: false, mutate: () => platform.sent.push('move') }),
  useRereadWorkflow: () => () => undefined,
}))

vi.mock('../../api/context', async (importOriginal) => ({ ...(await importOriginal<object>()), useErrorWords: () => () => 'The platform said no.' }))
vi.mock('../../ui/focus', async (importOriginal) => ({ ...(await importOriginal<object>()), useFocusAfterReread: () => () => undefined }))

const LIST = statuses as WatchlistView
const QUESTION = 'Turn off the schedule? The watchlist won’t be checked until someone sets one again.'
const DRAWN_OUT = [TurnOffSchedule, ConfirmLine, Button]

function schedule(version = LIST.version, shown = LIST.schedule): Drawn[] {
  return elementsOf(
    testHooks.draw(() => Schedule({ schedule: shown, version, operator: true, paused: false, useCaseId: LIST.use_case_id, answeredAt: 0, onResumed: () => undefined, held: null })),
    DRAWN_OUT,
  )
}

const questionIn = (elements: readonly Drawn[]) => elements.find((element) => element.props['role'] === 'group')
const labelsIn = (elements: readonly Drawn[]) => elements.filter((element) => element.type === 'button').map((element) => wordsOf(element))
const ask = () => press(buttonIn(schedule(), 'Turn off schedule'))

/** Gives a drawn button's ref a stand-in, so a test sees focus move to it. */
function watchFocus(button: Drawn) {
  const stand = { focus: vi.fn() }
  const ref = button.props['ref'] as { current: unknown } | ((node: unknown) => void)
  if (typeof ref === 'function') ref(stand)
  else ref.current = stand
  return stand.focus
}

/** Turn off schedule is not drawn while the question is open, so its ref comes from the question's own props. */
function watchOffButton(drawn: readonly Drawn[]) {
  const turnOff = drawn.find((element) => element.type === TurnOffSchedule)
  if (!turnOff) throw new Error('no Turn off schedule')
  const ref = turnOff.props['offButton'] as { current: unknown }
  const stand = { focus: vi.fn() }
  ref.current = stand
  return stand.focus
}

beforeEach(() => {
  testHooks.reset()
  platform.sent.length = 0
  platform.answers.length = 0
})

describe('turning off the watchlist schedule', () => {
  it('sends nothing on the first press of Turn off schedule, and asks in its place', () => {
    ask()
    expect(platform.sent).toEqual([])
    const drawn = schedule()
    expect(wordsOf(questionIn(drawn))).toContain(QUESTION)
    expect(labelsIn(drawn)).toEqual(['Keep it', 'Yes, turn it off'])
  })

  it('draws the question as a group described by its sentence, Keep it first with focus, and the destructive Yes last', () => {
    ask()
    const drawn = schedule()
    const group = questionIn(drawn)
    expect(group?.props['aria-label']).toBe('Turn off the schedule')
    expect(wordsOf(drawn.find((element) => element.props['id'] === group?.props['aria-describedby']))).toBe(QUESTION)
    expect(buttonIn(drawn, 'Yes, turn it off').props['className']).toMatch(/dangerOutline/)
    const focus = watchFocus(buttonIn(drawn, 'Keep it'))
    expect(focus).toHaveBeenCalledOnce()
  })

  it('changes nothing on Keep it, and gives focus back to Turn off schedule', () => {
    ask()
    const drawn = schedule()
    const backTo = watchOffButton(drawn)
    press(buttonIn(drawn, 'Keep it'))
    expect(platform.sent).toEqual([])
    expect(backTo).toHaveBeenCalledOnce()
    expect(labelsIn(schedule())).toEqual(['Change schedule', 'Turn off schedule'])
  })

  it('changes nothing on Escape, from either button', () => {
    for (const label of ['Keep it', 'Yes, turn it off']) {
      ask()
      expect(pressKey(buttonIn(schedule(), label), 'Escape').prevented).toBe(true)
      expect(questionIn(schedule())).toBeUndefined()
    }
    expect(platform.sent).toEqual([])
  })

  it('turns it off once on Yes, even pressed twice, then puts focus on the schedule button', () => {
    ask()
    const yes = buttonIn(schedule(), 'Yes, turn it off')
    press(yes)
    press(yes)
    expect(platform.sent).toEqual([`turn off ${LIST.version}`])
    const opener = watchFocus(buttonIn(schedule(LIST.version + 1, null), 'Set a schedule'))
    platform.answers[0]?.onSuccess?.()
    expect(opener).toHaveBeenCalledOnce()
  })

  it('gives focus back to Turn off schedule when the platform says no', () => {
    ask()
    const drawn = schedule()
    const backTo = watchOffButton(drawn)
    press(buttonIn(drawn, 'Yes, turn it off'))
    platform.answers[0]?.onError?.(new Error('no'))
    expect(backTo).toHaveBeenCalledOnce()
    expect(questionIn(schedule())).toBeUndefined()
  })

  it('shows no other schedule button while it asks', () => {
    ask()
    expect(labelsIn(schedule())).not.toContain('Change schedule')
  })

  it('closes the question when the watchlist changes, and never opens it again by itself', () => {
    ask()
    expect(questionIn(schedule(LIST.version + 1))).toBeUndefined()
    expect(questionIn(schedule(LIST.version + 1, null))).toBeUndefined()
    expect(questionIn(schedule(LIST.version + 2))).toBeUndefined()
    expect(platform.sent).toEqual([])
  })
})
