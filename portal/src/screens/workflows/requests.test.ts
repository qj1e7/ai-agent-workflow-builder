import { describe, expect, it } from 'vitest'
import { ApiError } from '../../api/client'
import type { FollowingUpItem, ReplyView, TeamRequestView } from '../../api/types'
import { followingWords, newestReplyToAsker, oneLine, requestPath, requestProblem } from './requests'

const NOW = new Date('2026-11-05T15:00:00+08:00')
const reply = (by: string, at: string, text = 'ok'): ReplyView => ({ replied_by: by, replied_by_name: by, replied_at: at, text, status: 'answered' })
const request = (replies: ReplyView[]): TeamRequestView => ({
  request_id: 'trq_1',
  kind: 'ask_the_team',
  about: { capability: 'email.send' },
  note: 'n',
  asked_by: 'alice',
  asked_by_name: 'Alice',
  asked_at: '2026-11-04T01:00:00Z',
  status: 'open',
  replies,
  posted_to_teams: true,
  not_posted_because: null,
})

describe('the link to a request', () => {
  it('is the address the Teams card opens', () => {
    expect(requestPath('trq_01JD5RP')).toBe('/workflows?request=trq_01JD5RP')
  })
})

describe('the reply the asker marks as read', () => {
  it('is the newest one from someone else, so their own notes never count', () => {
    const view = request([reply('bob', '2026-11-04T02:00:00Z'), reply('carol', '2026-11-04T03:00:00Z'), reply('alice', '2026-11-04T04:00:00Z')])
    expect(newestReplyToAsker(view)).toBe('2026-11-04T03:00:00Z')
  })

  it('is none when only the asker has written, or nobody has', () => {
    expect(newestReplyToAsker(request([reply('alice', '2026-11-04T04:00:00Z')]))).toBeNull()
    expect(newestReplyToAsker(request([]))).toBeNull()
  })
})

describe('a line under Following up', () => {
  const item: FollowingUpItem = { request_id: 'trq_1', kind: 'support', about: {}, note: 'It stopped again.', asked_at: '2026-11-05T01:00:00Z', status: 'open', latest_reply: null }

  it('says nobody has replied yet, or who answered and what', () => {
    expect(followingWords(item, NOW).sub).toBe('Platform problem · Today 9:00 · Open. Nobody has replied yet.')
    const answered = followingWords({ ...item, status: 'done', latest_reply: reply('Bob', '2026-11-05T02:00:00Z', 'Fixed.') }, NOW)
    expect(answered.sub).toContain('Done by Bob: Fixed.')
  })

  it('keeps long words to one line', () => {
    expect(oneLine('a\n  b   c')).toBe('a b c')
    expect(oneLine('x'.repeat(200))).toHaveLength(90)
    expect(followingWords({ ...item, note: 'y'.repeat(200) }, NOW).name).toHaveLength(90)
  })
})

describe('a request that cannot be shown', () => {
  it('is missing on a 404 and failed on anything else', () => {
    expect(requestProblem(new ApiError(404, null))).toBe('missing')
    expect(requestProblem(new ApiError(503, null))).toBe('failed')
    expect(requestProblem(new Error('offline'))).toBe('failed')
  })
})
