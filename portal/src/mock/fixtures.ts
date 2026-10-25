import refusalOwnWork from '@contracts/fixtures/approvals/refusal.own_work.json'
import templates from '@contracts/fixtures/builder/templates.json'
import cardList from '@contracts/fixtures/cards/list.json'
import planCannot from '@contracts/fixtures/cards/plan.cannot-do.json'
import planNewAgent from '@contracts/fixtures/cards/plan.new-agent.json'
import planUseOne from '@contracts/fixtures/cards/plan.use-one.json'
import cardTools from '@contracts/fixtures/cards/tools.json'
import useCase from '@contracts/fixtures/builder/use-case.json'
import cardRun from '@contracts/fixtures/runs/card.json'
import failureRun from '@contracts/fixtures/runs/failure.json'
import rejectedRun from '@contracts/fixtures/runs/rejected.json'
import successRun from '@contracts/fixtures/runs/success.json'
import watchlistRun from '@contracts/fixtures/runs/watchlist.json'
import devUsers from '@contracts/fixtures/stubs/dev-users.json'
import troubleshooting from '@contracts/fixtures/troubleshooting/failure.json'
import viewAwaiting from '@contracts/fixtures/views/success.awaiting_approval.json'
import viewRejected from '@contracts/fixtures/views/rejected.final.json'
import viewWatchlistAwaiting from '@contracts/fixtures/views/watchlist.awaiting_approval.json'
import watchlistBeforeCheck from '@contracts/fixtures/watchlist/before-check.json'
import type {
  ActivityEvent,
  CardView,
  DevUser,
  PlanOut,
  ProposalView,
  TemplateView,
  ToolView,
  TroubleshootingOut,
  UseCaseView,
  WatchlistView,
} from '../api/types'

// The JSON files are generated from the platform's models and checked in CI, so one cast per file is the boundary.
export const fixtures = {
  successEvents: successRun as ActivityEvent[],
  failureEvents: failureRun as ActivityEvent[],
  rejectedEvents: rejectedRun as ActivityEvent[],
  successProposal: viewAwaiting.proposal as ProposalView,
  rejectedProposal: viewRejected.proposal as ProposalView,
  watchlistEvents: watchlistRun as ActivityEvent[],
  watchlistProposal: viewWatchlistAwaiting.proposal as ProposalView,
  watchlistBeforeCheck: watchlistBeforeCheck as WatchlistView,
  useCase: useCase as UseCaseView,
  templates: templates.templates as TemplateView[],
  tools: cardTools.tools as ToolView[],
  cards: cardList.cards as CardView[],
  planUseOne: planUseOne as Extract<PlanOut, { decision: 'use_one' | 'use_several' }>,
  planNewAgent: planNewAgent as Extract<PlanOut, { decision: 'new_agent' }>,
  planCannot: planCannot as PlanOut,
  cardEvents: cardRun as ActivityEvent[],
  devUsers: devUsers.users as DevUser[],
  troubleshooting: troubleshooting as TroubleshootingOut,
  ownWorkRefusal: refusalOwnWork,
}
