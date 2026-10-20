import approvalAlice from '@contracts/fixtures/approvals/apr_01JB8.alice.json'
import viewFailureFinal from '@contracts/fixtures/views/failure.final.json'
import viewFailureWorking from '@contracts/fixtures/views/failure.working.json'
import viewAwaiting from '@contracts/fixtures/views/success.awaiting_approval.json'
import viewSuccessFinal from '@contracts/fixtures/views/success.final.json'
import viewRejectedFinal from '@contracts/fixtures/views/rejected.final.json'
import { describe, expect, it } from 'vitest'
import { fixtures } from './fixtures'
import { foldApprovals, foldView, type RunMeta } from './runView'

const meta = (id: string): RunMeta => ({
  id,
  useCaseId: fixtures.useCase.use_case_id,
  useCaseName: fixtures.useCase.name,
  useCaseVersion: 1,
  startedBy: 'alice',
})

const upTo = (events: typeof fixtures.successEvents, seq: number) => events.filter((event) => event.seq <= seq)

describe('the run view follows the events', () => {
  const proposals = [fixtures.successProposal, fixtures.rejectedProposal]

  it('matches the recorded view at the approval pause', () => {
    expect(foldView(meta('run_01JB8'), upTo(fixtures.successEvents, 17), proposals)).toEqual(viewAwaiting)
  })

  it('matches the recorded view when the run has succeeded', () => {
    expect(foldView(meta('run_01JB8'), fixtures.successEvents, proposals)).toEqual(viewSuccessFinal)
  })

  it('matches the recorded views of the failed run, while working and at the end', () => {
    expect(foldView(meta('run_01JB9'), upTo(fixtures.failureEvents, 6), proposals)).toEqual(viewFailureWorking)
    expect(foldView(meta('run_01JB9'), fixtures.failureEvents, proposals)).toEqual(viewFailureFinal)
  })

  it('matches the recorded view of the rejected run', () => {
    expect(foldView(meta('run_01JBA'), fixtures.rejectedEvents, proposals)).toEqual(viewRejectedFinal)
  })

  it('leaves the run pending until the first agent step starts', () => {
    expect(foldView(meta('run_01JB8'), upTo(fixtures.successEvents, 2), proposals).state).toBe('pending')
  })
})

describe('approvals follow the events', () => {
  it('opens at the request and records the decision on its step', () => {
    const [open] = foldApprovals('run_01JB8', upTo(fixtures.successEvents, 17), [fixtures.successProposal])
    expect(open?.steps[0]?.status).toBe('open')
    expect(open?.digest).toBe(approvalAlice.digest)

    const [decided] = foldApprovals('run_01JB8', fixtures.successEvents, [fixtures.successProposal])
    expect(decided?.steps[0]).toMatchObject({ status: 'approved', decided_by: 'bob' })
  })
})
