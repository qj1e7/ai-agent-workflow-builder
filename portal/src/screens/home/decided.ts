import type { DecidedReply, PastDecisionView } from '../../api/types'
import { count, factsOf, stageWords, type NameOf } from '../run/words'
import { lineWhen } from '../workflows/times'

type Only = DecidedReply['only']

const ONLY_WORDS = { approve: 'approved', decline: 'declined' } as const

/** "Here are your 2 decisions.", or for a question about declines alone, "You haven’t declined any requests yet." */
export function decidedSay(total: number, shown: number, only: Only): string {
  const said =
    only === null
      ? total === 0
        ? 'You haven’t decided on any requests yet.'
        : total === 1
          ? 'Here is your decision.'
          : `Here are your ${String(total)} decisions.`
      : total === 0
        ? `You haven’t ${ONLY_WORDS[only]} any requests yet.`
        : `You ${ONLY_WORDS[only]} ${count(total, 'request')}.`
  return shown < total ? `${said} The ${String(shown)} newest are here.` : said
}

/**
 * The line under a decision in the sketch's decisions card: the day, then the reason for a decline ("Tue 4 Nov · Not this week"), or
 * what the run did after a yes, in the stage words its run page, its card and the Workflows row use ("Today 9:10 · 1 ticket created").
 */
export function decisionSub(decision: PastDecisionView, now: Date, nameOf: NameOf): string {
  const day = lineWhen(decision.at, now)
  if (decision.verdict === 'decline') return decision.reason ? `${day} · ${decision.reason}` : day
  const facts = factsOf(decision.run_state, { count: decision.written, tickets: decision.tickets, declinedBy: decision.declined_by })
  return `${day} · ${stageWords(facts, nameOf)}`
}
