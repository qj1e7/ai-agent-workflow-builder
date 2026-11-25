import { describe, expect, it } from 'vitest'
import agentUseCase from '../../../../contracts/fixtures/cards/use-case.json'
import type { UseCaseView } from '../../api/types'
import { changePath, changeReply, editView, NO_PICKS } from './edit'

const USE_CASE = agentUseCase as UseCaseView

describe('Change on a workflow’s page', () => {
  it('opens Home with the workflow’s id in the address', () => {
    expect(changePath('uc_01JD0')).toBe('/?change=uc_01JD0')
    expect(changePath('uc a/b')).toBe('/?change=uc%20a%2Fb')
  })

  it('draws the edit card for that workflow from the workflow itself, with no model, and asks the day first', () => {
    const useCase: UseCaseView = { ...USE_CASE, schedule: { day: 'monday', at: '09:00', time_zone: 'Asia/Singapore', owner_name: 'Alice', held: null } }
    const reply = changeReply(useCase)
    expect(reply).toMatchObject({ answer: 'edit', use_case_id: useCase.use_case_id, name: useCase.name, watchlist: false, choices: [], cant: null, holds_save: false, trace_id: null })
    expect(reply.before).toEqual({ day: 'monday', at: '09:00' })
    expect(reply.after).toEqual({ day: null, at: null })
    const view = editView(reply, NO_PICKS, { kind: 'read', schedule: { day: 'monday', at: '09:00' }, version: useCase.version })
    expect(view.kind).toBe('ask')
  })

  it('has no before for a workflow that has no schedule', () => {
    expect(changeReply({ ...USE_CASE, schedule: null }).before).toBeNull()
  })
})
