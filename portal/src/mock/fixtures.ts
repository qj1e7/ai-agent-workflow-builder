import refusalOwnWork from '@contracts/fixtures/approvals/refusal.own_work.json'
import suggest from '@contracts/fixtures/builder/suggest.json'
import templates from '@contracts/fixtures/builder/templates.json'
import useCase from '@contracts/fixtures/builder/use-case.json'
import failureRun from '@contracts/fixtures/runs/failure.json'
import rejectedRun from '@contracts/fixtures/runs/rejected.json'
import successRun from '@contracts/fixtures/runs/success.json'
import devUsers from '@contracts/fixtures/stubs/dev-users.json'
import troubleshooting from '@contracts/fixtures/troubleshooting/failure.json'
import viewAwaiting from '@contracts/fixtures/views/success.awaiting_approval.json'
import viewRejected from '@contracts/fixtures/views/rejected.final.json'
import type {
  ActivityEvent,
  DevUser,
  ProposalView,
  TemplateView,
  TroubleshootingOut,
  UseCaseView,
} from '../api/types'

// The JSON files are generated from the platform's models and checked in CI, so one cast per file is the boundary.
export const fixtures = {
  successEvents: successRun as ActivityEvent[],
  failureEvents: failureRun as ActivityEvent[],
  rejectedEvents: rejectedRun as ActivityEvent[],
  successProposal: viewAwaiting.proposal as ProposalView,
  rejectedProposal: viewRejected.proposal as ProposalView,
  useCase: useCase as UseCaseView,
  templates: templates.templates as TemplateView[],
  releaseCheck: suggest.template as TemplateView,
  devUsers: devUsers.users as DevUser[],
  troubleshooting: troubleshooting as TroubleshootingOut,
  ownWorkRefusal: refusalOwnWork,
}
