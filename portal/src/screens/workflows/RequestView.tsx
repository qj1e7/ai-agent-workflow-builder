import { useEffect, useId, useRef, useState } from 'react'
import { Link } from 'react-router'
import { useErrorWords } from '../../api/context'
import { useLatch } from '../../api/latch'
import { useMe } from '../../api/queries'
import { useMarkRequestSeen, useReplyToRequest, useTeamRequest } from '../../api/requestQueries'
import type { TeamRequestView } from '../../api/types'
import { Button } from '../../ui/Button'
import { IconChevronLeft } from '../../ui/icons'
import { lineWhen } from './times'
import { MAX_REPLY, newestReplyToAsker, replyWords, requestKindWords, requestProblem, requestStatusWords } from './requests'
import styles from './Workflows.module.css'

const NOT_POSTED: Record<NonNullable<TeamRequestView['not_posted_because']>, string> = {
  posting: 'The card for Teams is still going out.',
  no_channel: 'No Teams channel is set up, so the team sees this request only here.',
  failed: 'The card did not reach Teams, so the team sees this request only here.',
}

function Back() {
  return (
    <Link to="/workflows" className={styles['back']}>
      <IconChevronLeft size={16} />
      Workflows
    </Link>
  )
}

export function RequestView({ requestId, now }: { requestId: string; now: Date }) {
  const request = useTeamRequest(requestId)
  if (request.isError) {
    const missing = requestProblem(request.error) === 'missing'
    return (
      <>
        <Back />
        <section className={styles['request']} aria-labelledby="request-problem">
          <h2 id="request-problem">{missing ? 'There is no request with that link' : 'The request could not be loaded'}</h2>
          <p>{missing ? 'The link may be wrong, or the request may have been removed. Your own requests are under Following up on Workflows.' : 'The platform did not answer as it should.'}</p>
          {missing ? null : <Button onClick={() => void request.refetch()}>Try again</Button>}
        </section>
      </>
    )
  }
  if (!request.data) {
    return (
      <>
        <Back />
        <p className="muted" role="status">
          Loading the request
        </p>
      </>
    )
  }
  return (
    <>
      <Back />
      <Request request={request.data} now={now} />
    </>
  )
}

function Request({ request, now }: { request: TeamRequestView; now: Date }) {
  const me = useMe().data
  const headingId = useId()
  const mine = me?.id === request.asked_by
  const through = newestReplyToAsker(request)
  const { mutate: markSeen } = useMarkRequestSeen(request.request_id)
  useEffect(() => {
    if (mine && through) markSeen(through)
  }, [mine, through, markSeen])
  const support = request.kind === 'support'
  const runId = request.about['run_id']
  return (
    <article className={styles['request']} aria-labelledby={headingId} data-request={request.request_id} data-status={request.status}>
      <h2 id={headingId}>{support ? `${mine ? 'You' : request.asked_by_name} reported a platform problem` : `${mine ? 'You' : request.asked_by_name} asked the team`}</h2>
      <p className={styles['requestMeta']}>
        <span className={styles['pill']} data-status={request.status}>
          {requestStatusWords(request.status)}
        </span>
        {requestKindWords(request.kind)} · {lineWhen(request.asked_at, now)}
      </p>
      <p className={styles['requestNote']}>{request.note}</p>
      {runId ? (
        <p>
          <Link to={`/runs/${runId}`}>See the run it is about</Link>
        </p>
      ) : null}
      {request.not_posted_because ? <p className="muted">{NOT_POSTED[request.not_posted_because]}</p> : null}
      <Replies request={request} now={now} />
      <ReplyForm requestId={request.request_id} mine={mine} />
    </article>
  )
}

function Replies({ request, now }: { request: TeamRequestView; now: Date }) {
  if (request.replies.length === 0) return <p className="muted">Nobody has replied yet.</p>
  return (
    <ol className={styles['replies']} aria-label="Replies">
      {request.replies.map((reply) => (
        <li key={`${reply.replied_by}:${reply.replied_at}`}>
          <b>{reply.replied_by_name}</b>
          <span className={styles['replyWhen']}>
            {lineWhen(reply.replied_at, now)} · {replyWords(reply, request.asked_by)}
          </span>
          <p>{reply.text}</p>
        </li>
      ))}
    </ol>
  )
}

function ReplyForm({ requestId, mine }: { requestId: string; mine: boolean }) {
  const reply = useReplyToRequest(requestId)
  const latch = useLatch()
  const words = useErrorWords()
  const [text, setText] = useState('')
  const [status, setStatus] = useState<'answered' | 'done'>('answered')
  const [sent, setSent] = useState(false)
  const [needText, setNeedText] = useState(false)
  const box = useRef<HTMLTextAreaElement>(null)
  const boxId = useId()
  const hintId = useId()
  const empty = text.trim() === ''

  function send(sets: 'answered' | 'done') {
    if (empty) {
      setNeedText(true)
      box.current?.focus()
      return
    }
    setNeedText(false)
    setSent(false)
    latch.run((settled) =>
      reply.mutate(
        { text: text.trim(), status: sets },
        {
          onSuccess: () => {
            setText('')
            setStatus('answered')
            setSent(true)
          },
          onSettled: settled,
        },
      ),
    )
  }

  return (
    <form
      className={styles['replyForm']}
      onSubmit={(event) => {
        event.preventDefault()
        send(mine ? 'answered' : status)
      }}
    >
      <h3>{mine ? 'Add to your request' : 'Reply'}</h3>
      <label htmlFor={boxId}>{mine ? 'Your note' : 'Your reply'}</label>
      <textarea id={boxId} ref={box} rows={4} maxLength={MAX_REPLY} value={text} onChange={(event) => {
          setText(event.target.value)
          setNeedText(false)
        }} aria-describedby={hintId} />
      <p id={hintId} className="muted">
        Everyone on the team can read this. Don’t paste passwords or keys. {mine ? 'Adding a note keeps the request as it is. Mark done when nothing more is needed.' : 'A reply changes no workflow and approves nothing.'}
      </p>
      {mine ? null : (
        <fieldset className={styles['replyStatus']}>
          <legend>After this reply, the request is</legend>
          <label>
            <input type="radio" name={`status-${boxId}`} checked={status === 'answered'} onChange={() => setStatus('answered')} />
            Answered
          </label>
          <label>
            <input type="radio" name={`status-${boxId}`} checked={status === 'done'} onChange={() => setStatus('done')} />
            Done, nothing more will happen
          </label>
        </fieldset>
      )}
      {needText ? (
        <p className={styles['problem']} role="alert">
          {mine ? 'Write a note first.' : 'Write a reply first.'}
        </p>
      ) : null}
      {reply.isError ? (
        <p className={styles['problem']} role="alert">
          Could not {mine ? 'add the note' : 'send the reply'}. {words(reply.error)}
        </p>
      ) : null}
      {sent ? <p role="status">{mine ? 'Added.' : 'Reply sent.'}</p> : null}
      <div className={styles['btns']}>
        <Button variant="primary" type="submit" loading={reply.isPending}>
          {mine ? 'Add' : 'Send reply'}
        </Button>
        {mine ? (
          <Button type="button" disabled={reply.isPending} onClick={() => send('done')}>
            Mark done
          </Button>
        ) : null}
      </div>
    </form>
  )
}
