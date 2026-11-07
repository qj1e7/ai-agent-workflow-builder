import { ApiError } from '../../api/client'
import type { FollowingUpItem, ReplyView, TeamRequestView } from '../../api/types'
import { lineWhen } from './times'

export const REQUEST_PARAM = 'request'

export const requestPath = (requestId: string) => `/workflows?${REQUEST_PARAM}=${encodeURIComponent(requestId)}`

export type RequestKind = TeamRequestView['kind']
export type RequestStatus = TeamRequestView['status']

export function requestKindWords(kind: RequestKind): string {
  return kind === 'support' ? 'Platform problem' : 'Ask the team'
}

const STATUS_WORDS: Record<RequestStatus, string> = { open: 'Open', answered: 'Answered', done: 'Done' }

export const requestStatusWords = (status: RequestStatus): string => STATUS_WORDS[status]

const LINE_SHOWN = 90

export function oneLine(words: string, limit = LINE_SHOWN): string {
  const flat = words.replace(/\s+/g, ' ').trim()
  return flat.length > limit ? `${flat.slice(0, limit - 1).trimEnd()}…` : flat
}

/** A request in the person's Following up list: what they asked, and where it stands. */
export function followingWords(item: FollowingUpItem, now: Date, meId: string | undefined): { readonly name: string; readonly sub: string } {
  const reply = item.latest_reply
  const stand = !reply
    ? `${requestStatusWords(item.status)}. Nobody has replied yet.`
    : reply.replied_by === meId
      ? `${requestStatusWords(item.status)}. You added: ${oneLine(reply.text, 70)}`
      : `${requestStatusWords(item.status)} by ${reply.replied_by_name}: ${oneLine(reply.text, 70)}`
  return { name: oneLine(item.note), sub: `${requestKindWords(item.kind)} · ${lineWhen(item.asked_at, now)} · ${stand}` }
}

/** What a reply did. The platform says so in the reply's status. */
export function replyWords(reply: ReplyView): string {
  switch (reply.status) {
    case 'done':
      return 'Marked Done'
    case 'added':
      return 'Added to the request'
    case 'answered':
      return 'Answered'
  }
}

/** The newest reply from someone other than the asker, which is the one the asker marks as read. */
export function newestReplyToAsker(request: TeamRequestView): string | null {
  const theirs = request.replies.filter((reply) => reply.replied_by !== request.asked_by)
  return theirs.length > 0 ? (theirs[theirs.length - 1]?.replied_at ?? null) : null
}

export const MAX_REPLY = 1000

export type NoRequest = 'missing' | 'failed'

export function requestProblem(error: unknown): NoRequest {
  return error instanceof ApiError && error.status === 404 ? 'missing' : 'failed'
}
