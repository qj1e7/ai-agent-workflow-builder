import type { ReactNode } from 'react'
import type { ExplainCleared, ExplainFlag, ExplainSetting, ExplainTouch, ExplainWrite, Segment, WorkflowExplained } from '../../api/types'
import styles from './Report.module.css'

/** A string from the plan or the document shows in curly quotes, apart from code's own words, so a block named “Security approved” can't read as a verdict. */
export function Words({ segments }: { segments: readonly Segment[] }): ReactNode {
  return segments.map((segment, index) =>
    segment.quoted ? (
      <span key={index} className={styles['quoted']}>
        “{segment.text}”
      </span>
    ) : (
      segment.text
    ),
  )
}

const Quoted = ({ text }: { text: string }): ReactNode => <Words segments={[{ text, quoted: true }]} />

const ACTION_LABEL = { reads: 'Reads', writes: 'Writes', posts: 'Posts' } as const

function Touch({ touch }: { touch: ExplainTouch }) {
  const place = touch.place === null ? null : <Quoted text={touch.place} />
  return (
    <div>
      <dt>{ACTION_LABEL[touch.action]}</dt>
      <dd>
        {touch.system === null && place === null ? <Words segments={touch.phrase} /> : null}
        {touch.system !== null ? <>{touch.system} </> : null}
        {place}
        <span className={styles['s']}>
          By <Quoted text={touch.block} />
          {touch.key === null ? '' : `, with the platform’s ${touch.key} key`}
        </span>
      </dd>
    </div>
  )
}

/** What it reads, writes and posts, one row for each, as the set-up approval draws it. */
export function Touches({ touches }: { touches: readonly ExplainTouch[] }) {
  if (touches.length === 0) return <p>It reads, writes and posts nothing.</p>
  return (
    <dl className={styles['touches']}>
      {touches.map((touch, index) => (
        <Touch key={index} touch={touch} />
      ))}
    </dl>
  )
}

/** One flag the check found, with where, why and what accepting it means. */
export function Flag({ flag }: { flag: ExplainFlag }) {
  return (
    <li>
      <b>{flag.what}</b>
      <span className={styles['s']}>
        {flag.block === null ? null : (
          <>
            In <Quoted text={flag.block} />.{' '}
          </>
        )}
        {flag.why} {flag.takes}
      </span>
    </li>
  )
}

/** Who decides each write, one row for each, as the set-up approval draws it. */
export function WhoApproves({ approves }: { approves: readonly ExplainWrite[] }) {
  if (approves.length === 0) return <p>It writes nothing, so nobody approves a write.</p>
  return (
    <ul className={styles['rows']}>
      {approves.map((write, index) => (
        <li key={index}>
          <b>
            <Quoted text={write.block} />
          </b>
          <span className={styles['s']}>{write.words}</span>
        </li>
      ))}
    </ul>
  )
}

function Setting({ setting }: { setting: ExplainSetting }) {
  return (
    <li>
      <b>
        <Words segments={setting.label} />
      </b>
      <span className={styles['s']}>{setting.value === null ? 'Not given yet' : <Words segments={setting.value} />}</span>
      <span className={styles['mark']} data-mark={setting.mark}>
        {setting.said}
      </span>
    </li>
  )
}

/** Each value it runs with, a write block's key among them, with where it came from or its mark, so a guess never reads as given. */
export function Settings({ settings }: { settings: readonly ExplainSetting[] }) {
  return (
    <ul className={styles['rows']}>
      {settings.map((setting, index) => (
        <Setting key={index} setting={setting} />
      ))}
    </ul>
  )
}

function Cleared({ title, items }: { title: string; items: readonly ExplainCleared[] }) {
  if (items.length === 0) return null
  return (
    <>
      <p className={styles['sub']}>{title}</p>
      <ul className={styles['ok']}>
        {items.map((item) => (
          <li key={item.rule}>{item.words}</li>
        ))}
      </ul>
    </>
  )
}

/** What code made sure of when it laid the workflow out, then every other rule no block breaks, in the safety checker's words. */
export function Checks({ report }: { report: Pick<WorkflowExplained, 'fixed' | 'passed'> }) {
  return (
    <>
      <Cleared title="Fixed for you" items={report.fixed} />
      <Cleared title="Passed" items={report.passed} />
    </>
  )
}
