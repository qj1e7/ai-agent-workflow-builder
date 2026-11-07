import { useId, useState, type ReactNode } from 'react'
import { Link } from 'react-router'
import { useNewWorkflowSteps } from '../../api/flags'
import type { CantReply, OfflineReply, PartReply, PlannerReply, SetupCardReply, WatchlistReply } from '../../api/types'
import { useCapabilities } from '../../api/plannerQueries'
import { Button, ButtonLink } from '../../ui/Button'
import { NEW_WORKFLOW_PATH } from '../new/starters'
import { AskTheTeam } from './AskTheTeam'
import { cantLines, cardLines, refusalNext, SAY_ANOTHER_WAY, setupTask, startingPoints, TAG_CANT, TAG_CHOICE, TAG_FILLED } from './answers'
import { CapabilityLists } from './CapabilityLists'
import { NewestAnswer, useMainButton } from './primary'
import { AddToWatchlist, WhichSoftware } from './WatchlistCard'
import styles from './Planner.module.css'

/** What a card can ask the page to do. Both go through the Planner or the box, so nothing here reaches a set-up on its own. */
export interface Page {
  /** Sends words to the Planner as a new question. */
  readonly ask: (text: string) => void
  /** Puts words back in the box for the person to change. */
  readonly edit: (text: string) => void
}

const OLD_NEW_WORKFLOW = 'Set it up in New workflow'

/**
 * The step that turns an answer into a workflow. Setting up from the card comes with the next change. Until then the
 * old New workflow is the way, while its flag is on. With the flag off, the card says plainly that it can't set up yet.
 */
function SetUp({ task, label = OLD_NEW_WORKFLOW, ask = 'here' }: { task: string; label?: string; ask?: 'here' | 'below' | 'above' }) {
  const oldNewWorkflow = useNewWorkflowSteps()
  const main = useMainButton()
  if (oldNewWorkflow) {
    return (
      <ButtonLink variant={main} to={NEW_WORKFLOW_PATH} state={{ task }}>
        {label}
      </ButtonLink>
    )
  }
  return (
    <>
      <p>Turning this on from Home isn’t built yet, so nothing was saved. Ask the team {ask === 'above' ? 'above' : 'below'} if you need it soon.</p>
      {ask === 'here' ? <AskTheTeam capability="setting up a workflow from Home" starter={`I asked the Planner for: ${task}\n\nIt was understood, but turning it on from Home is not built yet.`} /> : null}
    </>
  )
}

function tagClass(tag: string): string {
  return [styles['tag'], tag === TAG_CHOICE ? styles['tagChoice'] : undefined, tag === TAG_CANT ? styles['tagCant'] : undefined].filter(Boolean).join(' ')
}

function Lines({ rows }: { rows: SetupCardReply['rows'] }) {
  return (
    <ul className={styles['lines']}>
      {cardLines(rows).map((line) => (
        <li key={line.kind} className={styles['line']}>
          <span className={styles['label']}>{line.label}</span>
          <span>
            {line.text}
            {line.tag ? <span className={tagClass(line.tag)}>{line.tag}</span> : null}
            {line.note ? <span className={styles['note']}>{line.note}</span> : null}
          </span>
        </li>
      ))}
    </ul>
  )
}

function Card({ title, tag, children }: { title: string; tag?: string; children: ReactNode }) {
  const id = useId()
  return (
    <section className={styles['pcard']} aria-labelledby={id}>
      <div className={styles['pcardHead']}>
        <h3 id={id}>{title}</h3>
        {tag ? <span className={tagClass(tag)}>{tag}</span> : null}
      </div>
      {children}
    </section>
  )
}

export function SetupCardAnswer({ reply, typed, ownRows = false }: { reply: SetupCardReply | PartReply; typed: string; ownRows?: boolean }) {
  const left = reply.answer === 'part' ? cantLines(reply.cant) : []
  return (
    <Card title={reply.name} tag={TAG_FILLED}>
      <Lines rows={reply.rows} />
      {reply.similar ? (
        <p className={styles['alt']}>
          You already have a workflow with this name. <Link to={`/workflows/${encodeURIComponent(reply.similar.use_case_id)}`}>Open {reply.similar.name}</Link>
        </p>
      ) : null}
      {left.length > 0 ? (
        <div className={styles['pcardPart']}>
          <p>
            <b>What I can’t do yet</b>
          </p>
          <ul className={styles['lines']}>
            {left.map((line) => (
              <li key={line.text}>
                {line.text}
                {line.note ? <span className={styles['note']}>{line.note}</span> : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <div className={styles['footer']}>
        <SetUp task={setupTask(reply, typed, ownRows)} label={reply.answer === 'part' ? 'Set up the part I can do in New workflow' : OLD_NEW_WORKFLOW} ask={reply.answer === 'part' ? 'below' : 'here'} />
        {reply.answer === 'part' ? <AskTheTeam capability={reply.cant[0]?.system ?? left[0]?.text ?? 'part of a request'} starter={`I asked the Planner for: ${typed}\n\nWhat it can't do yet: ${left.map((line) => line.text).join('; ')}`} /> : null}
      </div>
    </Card>
  )
}

export function CantAnswer({ reply, typed }: { reply: CantReply; typed: string }) {
  const rows = cantLines(reply.cant)
  const alternative = reply.alternative
  return (
    <>
      <Card title="What I can’t do yet">
        <ul className={styles['lines']}>
          {rows.map((line) => (
            <li key={line.text}>
              <b>{line.text}</b>
              {line.note ? <span className={styles['note']}>{line.note}</span> : null}
            </li>
          ))}
        </ul>
        <div className={styles['footer']}>
          <AskTheTeam
            capability={reply.cant.find((row) => row.system)?.system ?? rows[0]?.text ?? 'something new'}
            starter={`I asked the Planner for: ${typed}\n\nIt can't do this yet: ${rows.map((line) => line.text).join('; ')}`}
            secondary={alternative !== null}
          />
        </div>
      </Card>
      {alternative?.answer === 'setup_card' ? (
        <Card title="What I can do instead">
          <Lines rows={alternative.rows} />
          <div className={styles['footer']}>
            <SetUp task={setupTask(reply, typed)} label="Set up the alternative in New workflow" ask="above" />
          </div>
        </Card>
      ) : null}
      {alternative?.answer === 'watchlist' ? <WatchlistAnswer reply={alternative} typed={typed} /> : null}
    </>
  )
}

export function WatchlistAnswer({ reply, typed }: { reply: WatchlistReply; typed: string }) {
  const listed = reply.already_listed
  const main = useMainButton()
  return (
    <>
      <Card title={listed ? 'Already on the watchlist' : 'The Software watchlist'}>
        <div className={styles['pcardPart']}>
          {listed ? (
            <>
              <p>{listed.name} is on the Software watchlist.</p>
              <div className={styles['buttons']}>
                <ButtonLink variant={main} to={`/software?row=${encodeURIComponent(listed.software_id)}`}>
                  Open it
                </ButtonLink>
              </div>
            </>
          ) : reply.software ? (
            <AddToWatchlist name={reply.software} />
          ) : (
            <div className={styles['buttons']}>
              <ButtonLink variant={main} to="/software">
                Open the Software watchlist
              </ButtonLink>
            </div>
          )}
        </div>
      </Card>
      {reply.also ? (
        <>
          <p>The rest of your request:</p>
          <NewestAnswer.Provider value={false}>
            <Answer reply={reply.also} typed={typed} page={NO_PAGE} ownRows />
          </NewestAnswer.Provider>
        </>
      ) : null}
    </>
  )
}

const NO_PAGE: Page = { ask: () => undefined, edit: () => undefined }

function RefusedAnswer({ reply, typed, page }: { reply: Extract<PlannerReply, { answer: 'refused' }>; typed: string; page: Page }) {
  const { rest } = refusalNext(reply)
  const main = useMainButton()
  return (
    <Card title="How approvals work">
      <div className={styles['pcardPart']}>
        <p>
          You asked me to skip a yes: <q>{reply.said}</q>. Any Approver on your team except you decides on your requests, in Teams. Nobody approves their own work, and nothing approves itself.
        </p>
        <p className="muted">{SAY_ANOTHER_WAY}</p>
        <div className={styles['buttons']}>
          {rest ? (
            <Button variant={main} onClick={() => page.ask(rest)}>
              Set it up with a yes
            </Button>
          ) : null}
          <Button variant={rest ? 'secondary' : main} onClick={() => page.edit(typed)}>
            Say it another way
          </Button>
        </div>
      </div>
    </Card>
  )
}

function AbilitiesAnswer() {
  const capabilities = useCapabilities()
  return (
    <>
      {capabilities.data ? (
        <CapabilityLists view={capabilities.data} />
      ) : (
        <p className="muted" role="status">
          {capabilities.isError ? 'I couldn’t load what I can do just now.' : 'Loading what I can do'}
        </p>
      )}
      <div className={styles['buttons']}>
        <AskTheTeam capability="something new" starter="I would like the Planner to be able to: " />
      </div>
    </>
  )
}

function IdeasAnswer({ page }: { page: Page }) {
  const capabilities = useCapabilities()
  if (!capabilities.data) {
    return (
      <p className="muted" role="status">
        {capabilities.isError ? 'I couldn’t load the ideas just now.' : 'Loading ideas'}
      </p>
    )
  }
  return (
    <ul className={styles['starters']}>
      {startingPoints(capabilities.data).map((text) => (
        <li key={text} className={styles['starter']}>
          <div>
            <b>{text}</b>
          </div>
          <Button onClick={() => page.ask(text)}>Use this</Button>
        </li>
      ))}
    </ul>
  )
}

export function OfflineAnswer({ reply }: { reply: OfflineReply }) {
  const oldNewWorkflow = useNewWorkflowSteps()
  const main = useMainButton()
  return (
    <>
      <ul className={styles['starters']}>
        {reply.starters.map((starter) => (
          <li key={starter.name} className={styles['starter']}>
            <div>
              <b>{starter.name}</b>
              <span className={styles['note']}>{starter.what}</span>
            </div>
            {starter.opens === 'software_watchlist' ? (
              <ButtonLink to="/software">Open the Software watchlist</ButtonLink>
            ) : oldNewWorkflow && starter.task ? (
              <ButtonLink to={NEW_WORKFLOW_PATH} state={{ task: starter.task }}>
                {OLD_NEW_WORKFLOW}
              </ButtonLink>
            ) : null}
          </li>
        ))}
      </ul>
      <div className={styles['buttons']}>
        <ButtonLink variant={main} to="/settings?tab=model">
          Connect a model
        </ButtonLink>
      </div>
    </>
  )
}

function Dismissable({ children }: { children: (never: () => void) => ReactNode }) {
  const [gone, setGone] = useState(false)
  return gone ? <p className="muted">All right, never mind.</p> : children(() => setGone(true))
}

interface AnswerProps {
  readonly reply: PlannerReply
  readonly typed: string
  readonly page: Page
  /** The answer is one half of a mixed request, so it hands on only its own rows. */
  readonly ownRows?: boolean
}

/** The body of one Planner answer, past its sentence. The three state answers are in StateAnswers. */
export function Answer({ reply, typed, page, ownRows = false }: AnswerProps) {
  switch (reply.answer) {
    case 'setup_card':
    case 'part':
      return <SetupCardAnswer reply={reply} typed={typed} ownRows={ownRows} />
    case 'cant':
      return <CantAnswer reply={reply} typed={typed} />
    case 'watchlist':
      return <WatchlistAnswer reply={reply} typed={typed} />
    case 'which_software':
      return <Dismissable>{(never) => <WhichSoftware onNever={never} />}</Dismissable>
    case 'refused':
      return <RefusedAnswer reply={reply} typed={typed} page={page} />
    case 'abilities':
      return <AbilitiesAnswer />
    case 'ideas':
      return <IdeasAnswer page={page} />
    case 'offline':
      return <OfflineAnswer reply={reply} />
    case 'check_workflows':
    case 'why_stopped':
    case 'needs_me':
      return null
  }
}

