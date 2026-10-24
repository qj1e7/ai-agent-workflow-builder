import { useId, useState } from 'react'
import { useErrorWords } from '../../api/context'
import {
  useConnectModel,
  useDecideAddress,
  useModelSettings,
  useSaveModel,
  useTurnModelOff,
} from '../../api/queries'
import type { Connected, ModelChangeOut, ModelOut, ModelSettingsView, PendingModelOut } from '../../api/types'
import { Button } from '../../ui/Button'
import { cx } from '../../ui/cx'
import { InlineMessage, Skeleton } from '../../ui/Feedback'
import { formatDayAndTime } from '../../ui/format'
import { IconCheck, IconReplay, IconX } from '../../ui/icons'
import { PageHeader } from '../../ui/PageHeader'
import {
  OTHER,
  addressFor,
  answerTime,
  connectBody,
  hostOf,
  maskedKey,
  missingForConnect,
  saveBody,
  savedKeyFits,
  startingChoice,
  suggestedModel,
  type Choice,
} from './modelForm'
import styles from './SettingsPage.module.css'

const BUILT_IN = 'the built-in sentence, for example “2 new releases: 1.2.16, 1.2.15”'
const FILTER_FROM = 8

export function SettingsPage() {
  const explain = useErrorWords()
  const settings = useModelSettings()

  return (
    <div className="page">
      <PageHeader title="Settings">Operators change these. Every change is recorded with who made it.</PageHeader>
      {settings.data ? <Loaded view={settings.data} /> : null}
      {!settings.data && settings.isError ? (
        <div className={styles['problem']}>
          <InlineMessage tone="error">We could not load the settings. {explain(settings.error)}</InlineMessage>
          <Button icon={IconReplay} loading={settings.isFetching} onClick={() => void settings.refetch()}>
            Try again
          </Button>
        </div>
      ) : null}
      {!settings.data && !settings.isError ? (
        <div className={`panel ${styles['section']}`}>
          <Skeleton lines={5} label="Loading settings" />
        </div>
      ) : null}
    </div>
  )
}

function Loaded({ view }: { view: ModelSettingsView }) {
  return (
    <div className={styles['sections']}>
      <section className={`panel ${styles['section']}`} aria-labelledby="model-title">
        <div className={styles['intro']}>
          <h2 id="model-title">AI model</h2>
          <p className="muted">
            Writes the one-sentence summary of each release check. Without a model, the platform uses its built-in
            sentence, so runs never stop because of the model.
          </p>
        </div>
        <Status active={view.active} />
        {view.pending ? <Pending pending={view.pending} active={view.active} /> : null}
        {!view.available ? <InlineMessage tone="error">{view.unavailable_message}</InlineMessage> : null}
        {view.you_can_change ? <ConnectForm view={view} /> : <ReadOnly view={view} />}
      </section>
      <Changes changes={view.changes} />
    </div>
  )
}

function Status({ active }: { active: ModelOut | null }) {
  if (!active) return <p className={styles['status']}>No AI model is set. Summaries use {BUILT_IN}.</p>
  return (
    <p className={cx(styles['status'], styles['statusOn'])}>
      Summaries are written by {active.model} ({active.provider}).
    </p>
  )
}

function Pending({ pending, active }: { pending: PendingModelOut; active: ModelOut | null }) {
  const explain = useErrorWords()
  const decide = useDecideAddress()
  const headingId = useId()
  const deciding = decide.isPending ? decide.variables.verdict : null

  return (
    <div className={styles['pending']} role="group" aria-labelledby={headingId}>
      <h3 id={headingId}>Waiting for an Approver to confirm a new address</h3>
      <p>
        {pending.by_name} asked to use {pending.model} at {pending.base_url}. It answered a test in{' '}
        {answerTime(pending.test_seconds)}. Until an Approver confirms it, runs keep using{' '}
        {active ? active.model : 'the built-in sentence'}.
      </p>
      {pending.you_can_decide ? (
        <div className={styles['actions']}>
          <Button
            variant="approve"
            icon={IconCheck}
            loading={deciding === 'confirm'}
            disabled={deciding === 'decline'}
            onClick={() => decide.mutate({ verdict: 'confirm', digest: pending.digest })}
          >
            Confirm the address
          </Button>
          <Button
            variant="danger-outline"
            icon={IconX}
            loading={deciding === 'decline'}
            disabled={deciding === 'confirm'}
            onClick={() => decide.mutate({ verdict: 'decline', digest: pending.digest })}
          >
            Decline
          </Button>
        </div>
      ) : (
        <p className="muted">{pending.why_not}</p>
      )}
      {decide.isError ? <InlineMessage tone="error">{explain(decide.error)}</InlineMessage> : null}
    </div>
  )
}

function ConnectForm({ view }: { view: ModelSettingsView }) {
  const explain = useErrorWords()
  const id = useId()
  const start = startingChoice(view)
  const [choice, setChoice] = useState<Choice>(start.choice)
  const [typed, setTyped] = useState(start.typed)
  const [key, setKey] = useState('')
  const [replacing, setReplacing] = useState(false)
  const [missing, setMissing] = useState<string | null>(null)
  const [model, setModel] = useState('')
  const connect = useConnectModel()
  const save = useSaveModel()
  const turnOff = useTurnModelOff()

  const address = addressFor(choice, view.providers, typed)
  const keyFits = savedKeyFits(view.active, address)
  const useSaved = keyFits && !replacing
  const found = connect.data?.status === 'connected' ? connect.data : null
  const busy = connect.isPending || save.isPending
  const options: { id: Choice; name: string; sub: string }[] = [
    ...view.providers.map((provider) => ({ id: provider.id, name: provider.name, sub: hostOf(provider.base_url) })),
    { id: OTHER, name: 'Another address', sub: 'An Approver confirms it once' },
  ]

  // Anything the Operator changes makes the last Connect and its answer out of date.
  function edited() {
    connect.reset()
    save.reset()
    turnOff.reset()
    setMissing(null)
  }

  function onConnect() {
    const gap = missingForConnect(choice, typed, key, useSaved)
    if (gap) {
      setMissing(gap)
      return
    }
    save.reset()
    turnOff.reset()
    connect.mutate(connectBody(choice, typed, key, useSaved), {
      onSuccess: (result) => {
        if (result.status === 'connected') setModel(suggestedModel(result.models))
      },
    })
  }

  function onSave() {
    if (!found) return
    save.mutate(saveBody(found, model, key, useSaved), {
      onSuccess: (result) => {
        if (result.status === 'problem') return
        setKey('')
        setReplacing(false)
        connect.reset()
      },
    })
  }

  return (
    <div className={styles['form']}>
      <h3>{view.active ? 'Change the model' : 'Connect a model'}</h3>
      <fieldset className={styles['fieldset']}>
        <legend>Where is the model?</legend>
        <div className={styles['providers']}>
          {options.map((option) => (
            <label key={option.id} className={cx(styles['option'], choice === option.id && styles['optionOn'])}>
              <input
                type="radio"
                name={`${id}-provider`}
                value={option.id}
                checked={choice === option.id}
                disabled={busy}
                onChange={() => {
                  setChoice(option.id)
                  setReplacing(false)
                  setKey('')
                  edited()
                }}
              />
              <span className={styles['dot']} aria-hidden="true" />
              <span className={styles['optionText']}>
                {option.name}
                <span className={styles['optionSub']}>{option.sub}</span>
              </span>
            </label>
          ))}
        </div>
      </fieldset>

      {choice === OTHER ? (
        <div className={styles['field']}>
          <label htmlFor={`${id}-address`}>Address</label>
          <input
            id={`${id}-address`}
            className={styles['input']}
            type="url"
            inputMode="url"
            autoComplete="off"
            spellCheck={false}
            placeholder="https://"
            value={typed}
            disabled={busy}
            aria-describedby={`${id}-address-help`}
            onChange={(event) => {
              setTyped(event.target.value)
              edited()
            }}
          />
          <p id={`${id}-address-help`} className={cx('muted', styles['help'])}>
            Any provider with an OpenAI-style or Anthropic-style API. A new address needs an Approver to confirm it once.
          </p>
        </div>
      ) : null}

      <div className={styles['field']}>
        {useSaved && view.active ? (
          <>
            <span className={styles['label']}>Key</span>
            <div className={styles['keyRow']}>
              <span className={styles['mask']} aria-label={`Saved key ending in ${view.active.key_hint}`}>
                {maskedKey(view.active.key_hint)}
              </span>
              <button
                type="button"
                className={styles['link']}
                disabled={busy}
                onClick={() => {
                  setReplacing(true)
                  edited()
                }}
              >
                Replace key
              </button>
            </div>
          </>
        ) : (
          <>
            <label htmlFor={`${id}-key`}>Key</label>
            <input
              id={`${id}-key`}
              className={styles['input']}
              type="password"
              autoComplete="off"
              spellCheck={false}
              placeholder="Paste the key"
              value={key}
              disabled={busy}
              aria-describedby={`${id}-key-help`}
              onChange={(event) => {
                setKey(event.target.value)
                edited()
              }}
            />
            <p id={`${id}-key-help`} className={cx('muted', styles['help'])}>
              Stored encrypted. After saving, nobody can read it again, only its last two characters.
            </p>
            {replacing && keyFits ? (
              <button
                type="button"
                className={styles['link']}
                onClick={() => {
                  setReplacing(false)
                  setKey('')
                  edited()
                }}
              >
                Use the saved key
              </button>
            ) : null}
          </>
        )}
      </div>

      {missing ? <InlineMessage tone="error">{missing}</InlineMessage> : null}

      {found ? (
        <ModelChoice
          found={found}
          name={options.find((option) => option.id === choice && choice !== OTHER)?.name ?? hostOf(found.base_url)}
          model={model}
          busy={busy}
          saving={save.isPending}
          onModel={(next) => {
            setModel(next)
            save.reset()
          }}
          onSave={onSave}
          onStartOver={edited}
        />
      ) : (
        <div className={styles['actions']}>
          <Button variant="primary" loading={connect.isPending} onClick={onConnect}>
            Connect
          </Button>
          {view.active ? (
            <Button variant="danger-outline" loading={turnOff.isPending} disabled={busy} onClick={() => turnOff.mutate()}>
              Turn the model off
            </Button>
          ) : null}
        </div>
      )}

      <div className={styles['results']}>
        {connect.data?.status === 'problem' ? <InlineMessage tone="error">{connect.data.message}</InlineMessage> : null}
        {connect.isError ? <InlineMessage tone="error">{explain(connect.error)}</InlineMessage> : null}
        {save.data?.status === 'saved' ? (
          <InlineMessage tone="success">
            Saved. The model answered in {answerTime(save.data.seconds)} with: “{save.data.text}”
          </InlineMessage>
        ) : null}
        {save.data?.status === 'awaiting_confirmation' ? (
          <p className={styles['wait']} role="status">
            Tested: the model answered in {answerTime(save.data.seconds)} with: “{save.data.text}” The address is new, so an
            Approver must confirm it before runs use it.
          </p>
        ) : null}
        {save.data?.status === 'problem' ? <InlineMessage tone="error">{save.data.message}</InlineMessage> : null}
        {save.isError ? <InlineMessage tone="error">{explain(save.error)}</InlineMessage> : null}
        {turnOff.isSuccess ? (
          <InlineMessage tone="success">The AI model is off. Summaries use the built-in sentence.</InlineMessage>
        ) : null}
        {turnOff.isError ? <InlineMessage tone="error">{explain(turnOff.error)}</InlineMessage> : null}
      </div>
    </div>
  )
}

interface ModelChoiceProps {
  found: Connected
  name: string
  model: string
  busy: boolean
  saving: boolean
  onModel: (model: string) => void
  onSave: () => void
  onStartOver: () => void
}

function ModelChoice({ found, name, model, busy, saving, onModel, onSave, onStartOver }: ModelChoiceProps) {
  const id = useId()
  const [filter, setFilter] = useState('')
  const wanted = filter.trim().toLowerCase()
  const shown = found.models.filter(
    (candidate) =>
      wanted === '' || candidate.id.toLowerCase().includes(wanted) || candidate.display.toLowerCase().includes(wanted),
  )
  const style = found.style === 'anthropic' ? 'Anthropic-style API' : 'OpenAI-style API'

  return (
    <div className={styles['found']}>
      <p className={styles['status']}>
        Connected to {name}. This key can use {found.models.length} {found.models.length === 1 ? 'model' : 'models'}.{' '}
        <span className={styles['detected']}>Detected: {style}.</span>
      </p>
      {found.models.length >= FILTER_FROM ? (
        <div className={styles['field']}>
          <label htmlFor={`${id}-filter`}>Find a model</label>
          <input
            id={`${id}-filter`}
            className={styles['input']}
            type="search"
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
          />
        </div>
      ) : null}
      <fieldset className={styles['fieldset']}>
        <legend>Model</legend>
        <div className={styles['models']}>
          {shown.map((candidate) => (
            <label key={candidate.id} className={cx(styles['option'], model === candidate.id && styles['optionOn'])}>
              <input
                type="radio"
                name={`${id}-model`}
                value={candidate.id}
                checked={model === candidate.id}
                disabled={busy}
                onChange={() => onModel(candidate.id)}
              />
              <span className={styles['dot']} aria-hidden="true" />
              <span className={styles['optionText']}>
                {candidate.display}
                {candidate.display !== candidate.id ? (
                  <span className={styles['optionSub']}>{candidate.id}</span>
                ) : null}
              </span>
              {candidate.suggested ? <span className={styles['chip']}>Suggested for summaries</span> : null}
            </label>
          ))}
          {shown.length === 0 ? <p className="muted">No model matches.</p> : null}
        </div>
      </fieldset>
      <div className={styles['actions']}>
        <Button variant="primary" loading={saving} disabled={model === ''} onClick={onSave}>
          Test and save
        </Button>
        <button type="button" className={styles['link']} disabled={busy} onClick={onStartOver}>
          Start over
        </button>
      </div>
    </div>
  )
}

function ReadOnly({ view }: { view: ModelSettingsView }) {
  const active = view.active
  return (
    <>
      {active ? (
        <dl className={styles['facts']}>
          <div>
            <dt>Provider</dt>
            <dd>{active.provider}</dd>
          </div>
          <div>
            <dt>Model</dt>
            <dd>{active.model}</dd>
          </div>
          <div>
            <dt>Key</dt>
            <dd>Ends in {active.key_hint}</dd>
          </div>
        </dl>
      ) : null}
      {view.available ? <p className="muted">Operators change settings. Approvers confirm new addresses.</p> : null}
    </>
  )
}

function Changes({ changes }: { changes: readonly ModelChangeOut[] }) {
  return (
    <section className={`panel ${styles['section']}`} aria-labelledby="changes-title">
      <h2 id="changes-title">Changes</h2>
      {changes.length === 0 ? (
        <p className="muted">No changes yet.</p>
      ) : (
        <ul className={styles['changes']}>
          {changes.map((change, index) => (
            <li key={`${change.at}-${index}`}>
              <time dateTime={change.at}>{formatDayAndTime(change.at)}</time>
              <span>{change.summary}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
