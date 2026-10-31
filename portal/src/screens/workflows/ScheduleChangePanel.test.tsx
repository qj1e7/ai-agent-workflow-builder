import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import agentUseCase from '../../../../contracts/fixtures/cards/use-case.json'
import type { ScheduleIn, UseCaseView } from '../../api/types'

const NEWER = agentUseCase as UseCaseView
const NOW = new Date('2026-11-04T15:00:00+08:00')
const saved = { ...NEWER, next_run_at: '2026-11-09T01:00:00Z' } as UseCaseView

const given = vi.hoisted(() => ({ form: null as null | { save: { mutate: (body: unknown, answers: unknown) => void }; work: string } }))

vi.mock('../software/Schedule', () => ({
  ScheduleForm: (props: NonNullable<typeof given.form>) => {
    given.form = props
    return null
  },
  useEditorThatRefocusesItsOpener: () => ({}),
}))
vi.mock('../../api/workflowQueries', () => ({
  useSaveWorkflowSchedule: () => ({ isPending: false, mutate: (_body: ScheduleIn, answers: { onSuccess: (view: UseCaseView) => void }) => answers.onSuccess(saved) }),
  useRereadWorkflow: () => () => undefined,
  useDeleteWorkflow: () => ({}),
  useMoveWorkflow: () => ({}),
}))

describe('the Change schedule panel', () => {
  it('says "runs", and tells the page what it saved and closes the form when the save works', async () => {
    const { ScheduleChangePanel } = await import('./WorkflowPage')
    const said: string[] = []
    const closed: string[] = []
    renderToStaticMarkup(<ScheduleChangePanel useCase={NEWER} now={NOW} onSaved={(words) => said.push(words)} onDone={() => undefined} />)

    given.form?.save.mutate({ day: 'monday', at: '09:00' }, { onSuccess: () => closed.push('closed'), onError: () => undefined })

    expect(given.form?.work).toBe('runs')
    expect(closed).toEqual(['closed'])
    expect(said).toEqual(['Saved. Next run Mon 9 Nov, 9:00.'])
  })
})
