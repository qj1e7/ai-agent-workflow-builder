import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { Navigate, useLocation, useNavigate, useSearchParams } from 'react-router'
import { useErrorWords } from '../../api/context'
import { newIdempotencyKey } from '../../api/idempotency'
import { useLatch } from '../../api/latch'
import { refusedWords, useDeleteDraft, useDrafts, usePlanFor, useSaveDraft, useUnderstand } from '../../api/newQueries'
import { useCreateAgentUseCase, useMe, useSaveCard } from '../../api/queries'
import { PRODUCT } from '../../shell/product'
import { Button } from '../../ui/Button'
import {
  afterReading,
  carryOn,
  changeRow,
  createBody,
  defaultName,
  draftContent,
  dropRow,
  EMPTY_FORM,
  enterWhen,
  nameProblem,
  taskWithoutSchedule,
  planView,
  restoreDraft,
  rowBlockers,
  STEP_NAMES,
  textProblem,
  whenProblems,
  type Form,
  type Planned,
  type Step,
  type WhenField,
} from './draft'
import { StepCheck } from './StepCheck'
import { StepDescribe } from './StepDescribe'
import { StepReview } from './StepReview'
import { StepWhen, whenFieldId } from './StepWhen'
import { draftGone, NEW_WORKFLOW_PATH, taskHandedOver } from './starters'
import styles from './NewWorkflow.module.css'

const LEAD = 'Describe a repeated task. Agents do it, and nothing changes without a yes.'
const DRAFT_GONE = 'That draft is gone. Start a new one.'
const WHEN_ORDER: readonly WhenField[] = ['often', 'day', 'at']

function Head({ step, saving, onSave }: { step: Step | null; saving?: boolean; onSave?: () => void }) {
  return (
    <div className={styles['head']}>
      <div>
        <h1 tabIndex={-1}>
          New workflow
          {step === null ? null : (
            <span className="visually-hidden">
              , step {step} of 4: {STEP_NAMES[step - 1]}
            </span>
          )}
        </h1>
        <p>{LEAD}</p>
      </div>
      {onSave ? (
        <button type="button" className={styles['linkButton']} aria-busy={saving || undefined} onClick={onSave}>
          Save draft and close
        </button>
      ) : null}
    </div>
  )
}

function Stepper({ step }: { step: Step }) {
  return (
    <>
      <ol className={styles['stepper']} aria-label="Steps">
        {STEP_NAMES.map((name, index) => (
          <li key={name} data-done={index + 1 < step || undefined} aria-current={index + 1 === step ? 'step' : undefined}>
            <div>
              {index + 1}.<span> {name}</span>
            </div>
          </li>
        ))}
      </ol>
      <p className={styles['stepNow']} aria-hidden="true">
        Step {step} of 4: {STEP_NAMES[step - 1]}
      </p>
    </>
  )
}

function useHeadingOnStep(step: Step, watchlist: boolean): void {
  const view = `${String(step)}:${String(watchlist)}`
  const shown = useRef(view)
  useEffect(() => {
    if (shown.current === view) return
    shown.current = view
    const heading = document.querySelector<HTMLElement>('main h1')
    if (!heading) return
    heading.focus()
    document.title = `${heading.textContent.trim()} · ${PRODUCT}`
  }, [view])
}

interface Start {
  readonly form: Form
  readonly plan: Planned | null
}

function NewWorkflow({ draftId, start }: { draftId: string | null; start: Start }) {
  const [form, setForm] = useState(start.form)
  const [draft, setDraft] = useState(draftId)
  const [textError, setTextError] = useState<string | null>(null)
  const [beat, setBeat] = useState(1)
  const [whenErrors, setWhenErrors] = useState<Partial<Record<WhenField, string>>>({})
  const [nameError, setNameError] = useState<string | null>(null)
  const [refused, setRefused] = useState<readonly string[]>([])
  const [saveError, setSaveError] = useState<string | null>(null)
  const [cards, setCards] = useState<Readonly<Record<string, string>>>({})
  const understand = useUnderstand()
  const saveDraft = useSaveDraft()
  const deleteDraft = useDeleteDraft()
  const saveCard = useSaveCard()
  const create = useCreateAgentUseCase()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const words = useErrorWords()
  const latch = useLatch()
  useHeadingOnStep(form.step, form.redirect !== null)

  const task = taskWithoutSchedule(form.rows)
  const rowsReady = form.step >= 2 && form.redirect === null && form.rows.length > 0 && rowBlockers(form.rows).length === 0
  const planned = start.plan?.task === task ? start.plan.answer : undefined
  const plan = usePlanFor(task, rowsReady, planned)
  const view = plan.data ? planView(plan.data, form.rows) : null

  useEffect(() => {
    if (!understand.isPending) return
    const timers = [700, 1400].map((ms, index) => setTimeout(() => setBeat(index + 2), ms))
    return () => timers.forEach(clearTimeout)
  }, [understand.isPending])

  const planIt = () => {
    const problem = textProblem(form.text)
    setTextError(problem)
    if (problem) {
      document.getElementById('task')?.focus()
      return
    }
    setBeat(1)
    latch.run((settled) =>
      understand.mutate(form.text.trim(), {
        onSuccess: (answer) => setForm((before) => afterReading({ ...before, plannerSaid: null }, answer)),
        onError: (error) => setForm((before) => ({ ...before, plannerSaid: words(error) })),
        onSettled: settled,
      }),
    )
  }

  const toWhen = () => setForm((before) => enterWhen({ ...before, step: 3 }))

  const toReview = () => {
    const problems = whenProblems(form.when)
    setWhenErrors(problems)
    const first = WHEN_ORDER.find((field) => problems[field])
    if (first) {
      document.getElementById(whenFieldId(first))?.focus()
      return
    }
    setForm((before) => ({ ...before, step: 4, name: before.name.trim() === '' ? defaultName(view) : before.name }))
  }

  const back = () => setForm((before) => ({ ...before, step: Math.max(1, before.step - 1) as Step }))

  const turnOn = () => {
    if (view?.kind !== 'agents') return
    const problem = nameProblem(form.name)
    setNameError(problem)
    if (problem) {
      document.getElementById('workflow-name')?.focus()
      return
    }
    latch.run((settled) => {
      void (async () => {
        try {
          const savedDrafts: Record<number, string> = {}
          for (const agent of view.agents) {
            if (agent.card.kind === 'saved') continue
            const key = `${task}#${String(agent.index)}`
            const id = cards[key] ?? (await saveCard.mutateAsync({ cardId: null, card: agent.card.definition })).card_id
            setCards((before) => ({ ...before, [key]: id }))
            savedDrafts[agent.index] = id
          }
          const made = await create.mutateAsync(createBody(form, view, savedDrafts))
          if (draft !== null) deleteDraft.mutate(draft)
          void queryClient.invalidateQueries({ queryKey: ['home'] })
          void navigate(`/new/done/${made.use_case_id}`, { replace: true })
        } catch (error) {
          const said = refusedWords(error)
          setRefused(said.length > 0 ? said : [words(error)])
        } finally {
          settled()
        }
      })()
    })
  }

  const saveAndClose = () => {
    if (form.step === 1 && form.text.trim() === '' && draft === null) {
      void navigate('/')
      return
    }
    const id = draft ?? newIdempotencyKey()
    setDraft(id)
    const content = draftContent(form, plan.data ? { task, answer: plan.data } : null)
    latch.run((settled) =>
      saveDraft.mutate(
        { draftId: id, draft: { step: form.step, content } },
        {
          onSuccess: () => void navigate('/'),
          onError: (error) => setSaveError(words(error)),
          onSettled: settled,
        },
      ),
    )
  }

  let body
  switch (form.step) {
    case 1:
      body = (
        <StepDescribe
          text={form.text}
          problem={textError}
          thinkingLines={understand.isPending ? beat : 0}
          plannerSaid={form.plannerSaid}
          onText={(text) => {
            setTextError(null)
            setForm((before) => ({ ...before, text }))
          }}
          onPlan={planIt}
        />
      )
      break
    case 2:
      body = (
        <StepCheck
          form={form}
          plan={{
            view,
            pending: plan.isFetching,
            error: plan.isError ? words(plan.error) : null,
            retry: () => void plan.refetch(),
          }}
          onChangeRow={(index, text) => setForm((before) => changeRow(before, index, text))}
          onDropRow={(index) => setForm((before) => dropRow(before, index))}
          onValue={(key, value) => setForm((before) => ({ ...before, typed: { ...before.typed, [key]: value } }))}
          onBack={back}
          onNext={toWhen}
          onCarryOn={() => setForm(carryOn)}
        />
      )
      break
    case 3:
      body = (
        <StepWhen
          when={form.when}
          asked={form.rows.find((row) => row.kind === 'schedule')?.text ?? ''}
          problems={whenErrors}
          onWhen={(when) => setForm((before) => ({ ...before, when }))}
          onBack={back}
          onNext={toReview}
        />
      )
      break
    case 4:
      body = view ? (
        <StepReview
          form={form}
          plan={view}
          nameProblem={nameError}
          busy={saveCard.isPending || create.isPending}
          problems={refused}
          onName={(name) => setForm((before) => ({ ...before, name }))}
          onBack={back}
          onTurnOn={turnOn}
        />
      ) : (
        <p className="muted" role="status">
          Planning the steps
        </p>
      )
      break
  }

  return (
    <div className={styles['page']}>
      <Head step={form.step} saving={saveDraft.isPending} onSave={saveAndClose} />
      {saveError ? (
        <p className={styles['error']} role="alert">
          {saveError}
        </p>
      ) : null}
      <Stepper step={form.step} />
      {body}
    </div>
  )
}

function OnlyOperators() {
  return (
    <div className={styles['page']}>
      <Head step={null} />
      <p>Only Operators set up workflows. Ask an Operator on your team.</p>
    </div>
  )
}

function Opening() {
  const [params] = useSearchParams()
  const location = useLocation()
  const draftId = params.get('draft')
  const drafts = useDrafts(draftId !== null)
  if (draftId === null) {
    const form = { ...EMPTY_FORM, text: taskHandedOver(location.state), plannerSaid: draftGone(location.state) ? DRAFT_GONE : null }
    return <NewWorkflow key="new" draftId={null} start={{ form, plan: null }} />
  }
  if (drafts.data && (drafts.isFetchedAfterMount || !drafts.isStale)) {
    const found = drafts.data.find((saved) => saved.draft_id === draftId)
    if (!found) return <Navigate to={NEW_WORKFLOW_PATH} replace state={{ draftGone: true }} />
    return <NewWorkflow key={draftId} draftId={draftId} start={restoreDraft(found)} />
  }
  if (drafts.isError)
    return (
      <div className={styles['page']}>
        <Head step={null} />
        <p>Your draft could not be loaded.</p>
        <Button onClick={() => void drafts.refetch()}>Try again</Button>
      </div>
    )
  return (
    <p className="muted" role="status">
      Loading your draft
    </p>
  )
}

export function NewWorkflowRoute() {
  const me = useMe()
  if (!me.data) return null
  return me.data.roles.includes('operator') ? <Opening /> : <OnlyOperators />
}
