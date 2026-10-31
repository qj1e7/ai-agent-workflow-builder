import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { Navigate, useLocation, useNavigate, useSearchParams } from 'react-router'
import { useErrorWords } from '../../api/context'
import { DRAFT_STEPS } from '../../api/drafts'
import { newIdempotencyKey } from '../../api/idempotency'
import { useLatch } from '../../api/latch'
import { isOperator } from '../../api/me'
import { refusedWords, useDeleteDraft, useDrafts, usePlanFor, useReadAgentCards, useSaveDraft, useUnderstand } from '../../api/newQueries'
import { useAgentCards, useCreateAgentUseCase, useMe, useSaveCard } from '../../api/queries'
import { PRODUCT } from '../../shell/product'
import { Button } from '../../ui/Button'
import {
  afterChecking,
  afterReading,
  carryOn,
  changeRow,
  checkOf,
  defaultName,
  draftContent,
  dropRow,
  EMPTY_FORM,
  enterWhen,
  nameProblem,
  taskWithoutSchedule,
  planView,
  restoreDraft,
  reusedAgents,
  rowBlockers,
  savedCopyOf,
  STEP_NAMES,
  textProblem,
  turnOn,
  whenProblems,
  type Form,
  type Planned,
  type Row,
  type Step,
  type WhenField,
} from './draft'
import { StepCheck } from './StepCheck'
import { StepDescribe } from './StepDescribe'
import { StepReview } from './StepReview'
import { StepWhen, whenFieldId } from './StepWhen'
import { draftGone, NEW_WORKFLOW_PATH, taskHandedOver } from './starters'
import styles from './NewWorkflow.module.css'

const DRAFT_GONE = 'That draft is gone. Start a new one.'
const WHEN_ORDER: readonly WhenField[] = ['often', 'day', 'at']

interface PageWords {
  readonly heading: string
  readonly lead: string
}

function Head({ page, step, saving, onSave }: { page: PageWords; step: Step | null; saving?: boolean; onSave?: () => void }) {
  return (
    <div className={styles['head']}>
      <div>
        <h1 tabIndex={-1}>
          {page.heading}
          {step === null ? null : (
            <span className="visually-hidden">
              , step {step} of {DRAFT_STEPS}: {STEP_NAMES[step - 1]}
            </span>
          )}
        </h1>
        <p>{page.lead}</p>
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
        Step {step} of {DRAFT_STEPS}: {STEP_NAMES[step - 1]}
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

function NewWorkflow({ page, draftId, start }: { page: PageWords; draftId: string | null; start: Start }) {
  const [form, setForm] = useState(start.form)
  const [draft, setDraft] = useState(draftId)
  const [textError, setTextError] = useState<string | null>(null)
  const [beat, setBeat] = useState(1)
  const [whenErrors, setWhenErrors] = useState<Partial<Record<WhenField, string>>>({})
  const [nameError, setNameError] = useState<string | null>(null)
  const [refused, setRefused] = useState<readonly string[]>([])
  const [saveError, setSaveError] = useState<string | null>(null)
  const understand = useUnderstand()
  const check = useUnderstand()
  const saveDraft = useSaveDraft()
  const deleteDraft = useDeleteDraft()
  const saveCard = useSaveCard()
  const readCards = useReadAgentCards()
  const me = useMe()
  const library = useAgentCards()
  const create = useCreateAgentUseCase()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const words = useErrorWords()
  const latch = useLatch()
  const cards = useRef(new Map<string, string>())
  useHeadingOnStep(form.step, form.redirect !== null)

  const task = taskWithoutSchedule(form.rows)
  const rowsReady = form.step >= 2 && form.redirect === null && form.rows.length > 0 && rowBlockers(form.rows).length === 0
  const planned = start.plan?.task === task ? start.plan.answer : undefined
  const plan = usePlanFor(task, rowsReady, planned)
  const view = plan.data ? planView(plan.data, form.rows) : null
  const reused = reusedAgents(view, library.data, me.data?.id)

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
      understand.mutate({ text: form.text.trim() }, {
        onSuccess: (answer) => setForm((before) => afterReading({ ...before, plannerSaid: null }, answer)),
        onError: (error) => setForm((before) => ({ ...before, plannerSaid: words(error) })),
        onSettled: settled,
      }),
    )
  }

  const checkPart = (asked: Form, part: Row) => {
    check.mutateAsync(checkOf(asked, part)).then(
      (answer) => setForm((before) => afterChecking(before, part, answer)),
      () => setForm((before) => afterChecking(before, part, null)),
    )
  }

  const reopened = useRef(false)
  useEffect(() => {
    if (reopened.current) return
    reopened.current = true
    for (const part of start.form.rows) if (part.state === 'checking') checkPart(start.form, part)
    // Only the parts a reopened draft sends back are checked here, once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const changePart = (index: number, text: string) => {
    const next = changeRow(form, index, text)
    setForm(next)
    const part = next.rows[index]
    if (part?.state === 'checking') checkPart(next, part)
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

  const pressTurnOn = () => {
    if (view?.kind !== 'agents') return
    const problem = nameProblem(form.name)
    setNameError(problem)
    if (problem) {
      document.getElementById('workflow-name')?.focus()
      return
    }
    latch.run((settled) => {
      turnOn(form, view, draft, cards.current, {
        savedCard: async (card) => (me.data ? savedCopyOf(await readCards(), me.data.id, card) : null),
        saveCard: async (card) => (await saveCard.mutateAsync({ cardId: null, card })).card_id,
        create: (body) => create.mutateAsync(body),
        deleteDraft: (draftId) => deleteDraft.mutateAsync(draftId),
      })
        .then(({ useCaseId, draftKept }) => {
          void queryClient.invalidateQueries({ queryKey: ['home'] })
          void navigate(`/new/done/${useCaseId}`, { replace: true, state: { draftKept } })
        })
        .catch((error: unknown) => {
          const said = refusedWords(error)
          setRefused(said.length > 0 ? said : [words(error)])
        })
        .finally(settled)
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
            reused,
          }}
          onChangeRow={changePart}
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
          reused={reused}
          nameProblem={nameError}
          busy={saveCard.isPending || create.isPending}
          problems={refused}
          onName={(name) => setForm((before) => ({ ...before, name }))}
          onBack={back}
          onTurnOn={pressTurnOn}
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
      <Head page={page} step={form.step} saving={saveDraft.isPending} onSave={saveAndClose} />
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

function OnlyOperators({ page }: { page: PageWords }) {
  return (
    <div className={styles['page']}>
      <Head page={page} step={null} />
      <p>Only Operators set up workflows. Ask an Operator on your team.</p>
    </div>
  )
}

function Opening({ page }: { page: PageWords }) {
  const [params] = useSearchParams()
  const location = useLocation()
  const draftId = params.get('draft')
  const drafts = useDrafts(draftId !== null)
  if (draftId === null) {
    const form = { ...EMPTY_FORM, text: taskHandedOver(location.state), plannerSaid: draftGone(location.state) ? DRAFT_GONE : null }
    return <NewWorkflow key="new" page={page} draftId={null} start={{ form, plan: null }} />
  }
  if (drafts.data && (drafts.isFetchedAfterMount || !drafts.isStale)) {
    const found = drafts.data.find((saved) => saved.draft_id === draftId)
    if (!found) return <Navigate to={NEW_WORKFLOW_PATH} replace state={{ draftGone: true }} />
    return <NewWorkflow key={draftId} page={page} draftId={draftId} start={restoreDraft(found)} />
  }
  if (drafts.isError)
    return (
      <div className={styles['page']}>
        <Head page={page} step={null} />
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

export function NewWorkflowRoute(page: PageWords) {
  const me = useMe()
  if (!me.data) return null
  return isOperator(me.data) ? <Opening page={page} /> : <OnlyOperators page={page} />
}
