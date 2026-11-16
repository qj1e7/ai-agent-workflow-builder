import { useState, type ReactNode } from 'react'
import type { ExplainFlag, ExplainSetting, ExplainTouch, Segment, WorkflowExplained } from '../../api/types'
import { gradePill } from '../workflows/n8nChange'
import { approvalGist, approvesGist, flagsGist, segmentsOfText, settingsGist, stepsGist, touchesGist } from './explain'
import styles from './Report.module.css'

/** A string from the plan or the document shows in curly quotes, apart from code's own words, so a block named “Security approved” can't read as a verdict. */
function Words({ segments }: { segments: readonly Segment[] }): ReactNode {
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

interface SectionProps {
  readonly title: string
  readonly gist: string
  readonly startOpen: boolean
  readonly children: ReactNode
}

/** A row with its gist, closed until a click or Enter opens it. The browser's own disclosure keeps the keyboard and the screen reader's state. */
function Section({ title, gist, startOpen, children }: SectionProps) {
  const [open, setOpen] = useState(startOpen)
  return (
    <details className={styles['section']} open={open} onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary>
        <span className={styles['title']}>{title}</span>
        <span className={styles['gist']}>{gist}</span>
      </summary>
      <div className={styles['body']}>{children}</div>
    </details>
  )
}

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

function Flag({ flag }: { flag: ExplainFlag }) {
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

interface ReportProps {
  readonly report: WorkflowExplained
  readonly code?: boolean
  /** Swaps between the reworded In short and code's. Only the chat card gives it. */
  readonly onWording?: () => void
}

/**
 * The workflow report (layout B): In short first, then one row per section with its gist. The chat card, the side panel and the
 * full page draw this one component. Everything under In short is code's own words. Settings opens by itself while an answer is needed.
 */
export function Report({ report, code = false, onWording }: ReportProps) {
  const rewordedShown = report.reworded !== null && !code
  const thenGrade = report.then === null ? null : gradePill(report.then.grade).label
  return (
    <div className={styles['report']}>
      <p className={styles['short']} data-in-short>
        <Words segments={rewordedShown && report.reworded !== null ? segmentsOfText(report.reworded) : report.in_short} />
      </p>
      {report.reworded !== null && onWording ? (
        <p className={styles['wording']}>
          <span className={styles['label']}>{rewordedShown ? 'Reworded' : 'Code’s wording'}</span>
          <button type="button" className={styles['linkButton']} onClick={onWording}>
            {rewordedShown ? 'Show code’s wording' : 'Show the reworded one'}
          </button>
        </p>
      ) : null}
      {report.then !== null && thenGrade !== null ? (
        <p className={styles['version']}>
          Version {report.then.number}. Checked again under today’s rules. Graded {thenGrade} when it was published, and {gradePill(report.grade).label} today.
        </p>
      ) : null}
      <div className={styles['sections']}>
        <Section title="Step by step" gist={stepsGist(report.steps)} startOpen={false}>
          <ol className={styles['steps']}>
            {report.steps.map((step, index) => (
              <li key={index}>
                <b>
                  <Quoted text={step.name} />
                </b>
                <span className={styles['s']}>
                  {step.tag}
                  {step.block_type === null ? '' : ` · ${step.ours ? 'our block' : 'n8n block'}, ${step.block_type}`}
                </span>
              </li>
            ))}
          </ol>
        </Section>
        <Section title="What it reads, writes and posts" gist={touchesGist(report.touches)} startOpen={false}>
          {report.touches.length === 0 ? (
            <p>It reads, writes and posts nothing.</p>
          ) : (
            <dl className={styles['touches']}>
              {report.touches.map((touch, index) => (
                <Touch key={index} touch={touch} />
              ))}
            </dl>
          )}
        </Section>
        <Section title="Flags" gist={flagsGist(report)} startOpen={false}>
          {report.flags.length === 0 ? <p>No flags.</p> : <ul className={styles['rows']}>{report.flags.map((flag, index) => <Flag key={index} flag={flag} />)}</ul>}
          {report.fixed.length > 0 ? (
            <>
              <p className={styles['sub']}>Fixed for you</p>
              <ul className={styles['ok']}>
                {report.fixed.map((item) => (
                  <li key={item.rule}>{item.words}</li>
                ))}
              </ul>
            </>
          ) : null}
          {report.passed.length > 0 ? (
            <>
              <p className={styles['sub']}>Passed</p>
              <ul className={styles['ok']}>
                {report.passed.map((item) => (
                  <li key={item.rule}>{item.words}</li>
                ))}
              </ul>
            </>
          ) : null}
        </Section>
        <Section title="Who approves each write" gist={approvesGist(report.approves)} startOpen={false}>
          {report.approves.length === 0 ? (
            <p>It writes nothing, so nobody approves a write.</p>
          ) : (
            <ul className={styles['rows']}>
              {report.approves.map((write, index) => (
                <li key={index}>
                  <b>
                    <Quoted text={write.block} />
                  </b>
                  <span className={styles['s']}>{write.words}</span>
                </li>
              ))}
            </ul>
          )}
        </Section>
        <Section title="Settings" gist={settingsGist(report.settings)} startOpen={report.needs_an_answer > 0}>
          <ul className={styles['rows']}>
            {report.settings.map((setting, index) => (
              <Setting key={index} setting={setting} />
            ))}
          </ul>
        </Section>
        <Section title="Approval" gist={approvalGist(report.approval)} startOpen={false}>
          <p>{report.approval}</p>
        </Section>
      </div>
    </div>
  )
}
