import type { DecidedReply, PastDecisionView } from '../../api/types'
import { count, declineTail, factsOf, sentence, stageWords, type NameOf } from '../run/words'
import { runWhen } from '../workflows/times'

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

/** " at 9:10 today", or ", Mon 26 Oct, 8:00", after "Approved by Bob". */
function decidedAt(at: string, now: Date): string {
  const when = runWhen(at, now)
  return when.startsWith('Today, ') ? ` at ${when.slice('Today, '.length)} today` : `, ${when}`
}

/**
 * What the run did after a yes, in the stage words its run page, its card and the Workflows row use. The line already says who
 * approved, so the words don't name them again.
 */
function afterYes(decision: PastDecisionView, nameOf: NameOf): string {
  const facts = factsOf(decision.run_state, { count: decision.written, tickets: decision.tickets, declinedBy: decision.declined_by })
  return sentence(stageWords(facts, nameOf))
}

/**
 * One decision in a line, as the run page and Teams say it: "Approved by Bob, Mon 26 Oct, 8:00. 1 ticket created.", or the
 * declined record with when, "Declined by Bob at 9:10 today. Nothing was written. Reason: Wrong version."
 */
export function decisionLine(decision: PastDecisionView, me: string, now: Date, nameOf: NameOf): string {
  const at = decidedAt(decision.at, now)
  const who = nameOf(me)
  if (decision.verdict === 'approve') return `Approved by ${who}${at}. ${afterYes(decision, nameOf)}`
  const before = decision.approved_before.map(nameOf)
  const head = before.length > 0 ? `Approved by ${before.join(', then ')}, then declined by ${who}${at}` : `Declined by ${who}${at}`
  return `${head}. ${declineTail({ reason: decision.reason })}`
}
