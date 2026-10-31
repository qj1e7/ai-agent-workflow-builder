import { useRef, useState, type FormEvent } from 'react'
import { ApiError } from '../../api/client'
import { useLatch } from '../../api/latch'
import { useConnectModel, useDecideAddress, useModelSettings, useSaveModel } from '../../api/queries'
import type { ConnectIn, Connected, ModelOut, ModelSettingsView, PendingModelOut, SaveIn } from '../../api/types'
import { Button } from '../../ui/Button'
import { cx } from '../../ui/cx'
import { CheckMark, ShieldMark } from './marks'
import {
  activeModelWords,
  fieldOfProblem,
  hostOf,
  keyHint,
  NO_KEY_IN_HISTORY_WORDS,
  ONLY_OPERATORS_WORDS,
  OTHER_ADDRESS,
  savedKeyFits,
  secondsWords,
  SETTINGS_OFF_WORDS,
  startingProvider,
  type ModelField,
  type ProviderChoice,
} from './settings'
import { FieldError, History, useFocusOnNextRender, useSettingsWords } from './SettingsParts'
import styles from './Settings.module.css'

const MODEL_IDS = {
  now: 'model-now',
  waiting: 'model-waiting',
  provider: 'model-provider',
  address: 'model-address',
  key: 'model-key',
  model: 'model-choice',
  submit: 'model-submit',
} as const

const ERROR_IDS: Record<ModelField, string> = {
  address: 'model-address-error',
  key: 'model-key-error',
  model: 'model-choice-error',
  form: 'model-form-error',
}

const FOCUS_FOR: Record<ModelField, string> = {
  address: MODEL_IDS.address,
  key: MODEL_IDS.key,
  model: MODEL_IDS.model,
  form: MODEL_IDS.submit,
}

// Without a model, an agent workflow run gets 409 "Connect an AI model in Settings to run agents." and planning gets 409 too.
// Only the watchlist check's summary falls back to a template.
export const NO_MODEL_WORDS = 'Until you connect one, agent workflows can’t run and new workflows can’t be planned. Only the Software watchlist’s summary uses a simple template instead.'
const WITHOUT_A_MODEL = 'agent workflows can’t run, and only the Software watchlist’s summary uses a simple template'

/** What runs do until a new address is confirmed, after "Until then, ". */
const untilThenWords = (active: ModelOut | null) => (active ? `runs keep using ${active.model}` : WITHOUT_A_MODEL)

export function notNowWords(active: ModelOut | null): string {
  const then = untilThenWords(active)
  return `You said not now. ${then.charAt(0).toUpperCase()}${then.slice(1)}.`
}

export const MODEL_READ_ONLY_WORDS = `${ONLY_OPERATORS_WORDS} Approvers confirm a new address before runs use it.`

type Errors = Partial<Record<ModelField, string>>

const describedBy = (...ids: (string | false | undefined)[]) => ids.filter(Boolean).join(' ') || undefined

export function ModelTab() {
  const settings = useModelSettings()
  const words = useSettingsWords()
  if (settings.isPending) {
    return (
      <section className={styles['panel']} aria-label="AI model">
        <p className="muted" role="status">
          Loading
        </p>
      </section>
    )
  }
  if (settings.isError) {
    return (
      <section className={styles['panel']} aria-label="AI model">
        <p role="status">{words(settings.error)}</p>
        <div className={styles['buttons']}>
          <Button onClick={() => void settings.refetch()}>Try again</Button>
        </div>
      </section>
    )
  }
  return <ModelPanel view={settings.data} />
}

type Verdict = 'confirm' | 'decline'

function ModelPanel({ view }: { view: ModelSettingsView }) {
  const [said, setSaid] = useState<string | null>(null)
  const [announced, setAnnounced] = useState('')
  const [pressed, setPressed] = useState<Verdict | null>(null)
  const [problem, setProblem] = useState<string | null>(null)
  const words = useSettingsWords()
  // React Query drops a mutate call's callbacks once its component unmounts, and the waiting box unmounts as the decision lands.
  const decide = useDecideAddress()
  const latch = useLatch()
  const focus = useFocusOnNextRender()

  function tell(words: string, where: 'now' | 'waiting') {
    setSaid(where === 'now' ? words : null)
    setAnnounced(words)
    focus(where === 'now' ? MODEL_IDS.now : MODEL_IDS.waiting)
  }

  function onDecide(pending: PendingModelOut, verdict: Verdict) {
    const active = view.active
    latch.run((settled) => {
      setProblem(null)
      setPressed(verdict)
      decide.mutate(
        { verdict, digest: pending.digest },
        {
          onSuccess: () => tell(verdict === 'confirm' ? `Confirmed. Runs now use ${pending.model}.` : notNowWords(active), 'now'),
          onError: (error) => {
            const why = words(error, 'address')
            setProblem(why)
            setAnnounced(why)
          },
          onSettled: () => {
            setPressed(null)
            settled()
          },
        },
      )
    })
  }

  return (
    <section className={styles['panel']} aria-labelledby="model-heading">
      <h2 id="model-heading">AI model</h2>
      <p className={styles['note']}>The model the agents use to plan, write and explain.</p>
      {!view.available ? <p className={styles['note']}>{SETTINGS_OFF_WORDS}</p> : !view.you_can_change ? <p className={styles['note']}>{MODEL_READ_ONLY_WORDS}</p> : null}
      <p className="visually-hidden" role="status">
        {announced}
      </p>
      <CurrentModel active={view.active} said={said} />
      {view.pending ? (
        <WaitingAddress
          pending={view.pending}
          active={view.active}
          pressed={pressed}
          problem={problem}
          onDecide={onDecide}
        />
      ) : null}
      {view.you_can_change ? <ModelForm view={view} onSaved={tell} announce={setAnnounced} /> : null}
      <History area="model" note={NO_KEY_IN_HISTORY_WORDS} />
    </section>
  )
}

function CurrentModel({ active, said }: { active: ModelOut | null; said: string | null }) {
  return (
    <div id={MODEL_IDS.now} tabIndex={-1} className={styles['now']}>
      {active ? (
        <>
          <span className={styles['pill']} data-tone="ok">
            <CheckMark size={12} />
            Connected
          </span>
          <div>
            <b>
              {active.provider} · {active.model}
            </b>
            <span className={styles['small']}>{activeModelWords(active)}</span>
          </div>
        </>
      ) : (
        <>
          <span className={styles['pill']} data-tone="off">
            Not connected
          </span>
          <div>
            <b>No AI model yet</b>
            <span className={styles['small']}>{NO_MODEL_WORDS}</span>
          </div>
        </>
      )}
      {said ? <p className={styles['said']}>{said}</p> : null}
    </div>
  )
}

interface WaitingProps {
  pending: PendingModelOut
  active: ModelOut | null
  pressed: Verdict | null
  problem: string | null
  onDecide: (pending: PendingModelOut, verdict: Verdict) => void
}

function WaitingAddress({ pending, active, pressed, problem, onDecide }: WaitingProps) {
  return (
    <div id={MODEL_IDS.waiting} tabIndex={-1} className={styles['waiting']}>
      <ShieldMark size={20} />
      <div>
        <b>A new address is waiting for an Approver</b>
        <span>
          {pending.base_url} · {pending.model}. Entered by {pending.by_name}. It answered the test in {secondsWords(pending.test_seconds)}. Agents
          send their prompts to this address, so someone else must confirm it. Until then, {untilThenWords(active)}.
        </span>
        {pending.you_can_decide ? null : <span>{pending.why_not ?? 'Waiting for an Approver.'}</span>}
        <FieldError id="model-waiting-error" words={problem ?? undefined} />
      </div>
      {pending.you_can_decide ? (
        <div className={styles['buttons']}>
          <Button variant="danger-outline" loading={pressed === 'decline'} onClick={() => onDecide(pending, 'decline')}>
            Not now
          </Button>
          <Button variant="approve" loading={pressed === 'confirm'} onClick={() => onDecide(pending, 'confirm')}>
            Confirm address
          </Button>
        </div>
      ) : null}
    </div>
  )
}

interface FormProps {
  view: ModelSettingsView
  onSaved: (words: string, where: 'now' | 'waiting') => void
  announce: (words: string) => void
}

function ModelForm({ view, onSaved, announce }: FormProps) {
  const words = useSettingsWords()
  const connect = useConnectModel()
  const save = useSaveModel()
  const latch = useLatch()
  const focus = useFocusOnNextRender()
  const [provider, setProvider] = useState<ProviderChoice>(() => startingProvider(view.providers, view.active))
  const [address, setAddress] = useState(() => (view.active && startingProvider(view.providers, view.active) === OTHER_ADDRESS ? view.active.base_url : ''))
  const [showKey, setShowKey] = useState(false)
  const [found, setFound] = useState<Connected | null>(null)
  const [model, setModel] = useState('')
  const [errors, setErrors] = useState<Errors>({})
  const keyInput = useRef<HTMLInputElement>(null)
  const keyToSave = useRef('')

  const known = view.providers.find((entry) => entry.id === provider)
  const url = known ? known.base_url : address.trim()
  const keepsKey = savedKeyFits(view.active, url)
  const providerName = known?.name ?? hostOf(address) ?? 'the address'
  const heading = view.active ? 'Change the model or key' : 'Connect a model'

  function fail(next: Errors) {
    setErrors(next)
    const first = (['address', 'key', 'model', 'form'] as const).find((field) => next[field])
    if (first) {
      focus(FOCUS_FOR[first])
      announce(next[first] ?? '')
    }
  }

  function onConnect(event: FormEvent) {
    event.preventDefault()
    const key = keyInput.current?.value.trim() ?? ''
    const problems: Errors = {}
    if (!known && !address.trim()) problems.address = 'Type the address your provider gave you.'
    if (!key && !keepsKey) problems.key = 'Paste the API key from your provider.'
    if (Object.keys(problems).length > 0) {
      fail(problems)
      return
    }
    const where = known ? { provider_id: known.id } : { base_url: address.trim() }
    const body: ConnectIn = key ? { ...where, api_key: key, use_saved_key: false } : { ...where, use_saved_key: true }
    latch.run((settled) => {
      setErrors({})
      connect.mutate(body, {
        onSuccess: (result) => {
          if (result.status === 'problem') {
            fail({ [fieldOfProblem(result.reason, 'key', !known)]: result.message })
            return
          }
          keyToSave.current = key
          const models = [...result.models].sort((a, b) => Number(b.suggested) - Number(a.suggested))
          setFound({ ...result, models })
          setModel(models[0]?.id ?? '')
          focus(MODEL_IDS.model)
          announce(`Connected to ${providerName}. Choose a model.`)
        },
        onError: (error) => fail({ [error instanceof ApiError && error.status === 409 ? 'key' : 'form']: words(error, 'address') }),
        onSettled: () => {
          connect.reset()
          settled()
        },
      })
    })
  }

  function startOver() {
    keyToSave.current = ''
    setFound(null)
    setErrors({})
    setShowKey(false)
  }

  function onSave(event: FormEvent) {
    event.preventDefault()
    if (!found) return
    const key = keyToSave.current
    const target = { style: found.style, base_url: found.base_url, model }
    const body: SaveIn = key ? { ...target, api_key: key, use_saved_key: false } : { ...target, use_saved_key: true }
    latch.run((settled) => {
      setErrors({})
      save.mutate(body, {
        onSuccess: (result) => {
          if (result.status === 'problem') {
            fail({ model: result.message })
            return
          }
          startOver()
          const secs = secondsWords(result.seconds)
          if (result.status === 'saved') onSaved(`Saved. ${model} answered in ${secs}. Agents use it from their next run.`, 'now')
          else onSaved(`${model} answered in ${secs}. An Approver must confirm the new address before runs use it.`, 'waiting')
        },
        onError: (error) => fail({ model: words(error, 'address') }),
        onSettled: () => {
          save.reset()
          settled()
        },
      })
    })
  }

  function cancel() {
    startOver()
    focus(MODEL_IDS.provider)
  }

  if (found) {
    return (
      <form className={styles['form']} onSubmit={onSave} noValidate aria-labelledby="model-form-heading">
        <h3 id="model-form-heading">{heading}</h3>
        <p className={styles['found']}>
          <CheckMark size={16} />
          <span>
            Connected to {providerName}. It offers {found.models.length === 1 ? '1 model' : `${found.models.length} models`} that can chat. The suggested one is first.
          </span>
        </p>
        <div className={styles['field']}>
          <label htmlFor={MODEL_IDS.model}>Model</label>
          <select
            id={MODEL_IDS.model}
            className={styles['select']}
            value={model}
            onChange={(event) => setModel(event.target.value)}
            aria-invalid={errors.model ? true : undefined}
            aria-describedby={describedBy('model-choice-help', errors.model && ERROR_IDS.model)}
          >
            {found.models.map((entry) => (
              <option key={entry.id} value={entry.id}>
                {entry.suggested ? `${entry.display} (suggested)` : entry.display}
              </option>
            ))}
          </select>
          <span className={styles['help']} id="model-choice-help">
            Test and save sends one short question. It saves only if the model answers within 10 seconds.
          </span>
          <FieldError id={ERROR_IDS.model} words={errors.model} />
        </div>
        <div className={styles['buttons']}>
          <Button id={MODEL_IDS.submit} type="submit" variant="primary" loading={save.isPending}>
            {save.isPending ? 'Testing' : 'Test and save'}
          </Button>
          <Button onClick={cancel}>Cancel</Button>
        </div>
      </form>
    )
  }

  return (
    <form className={styles['form']} onSubmit={onConnect} noValidate aria-labelledby="model-form-heading">
      <h3 id="model-form-heading">{heading}</h3>
      <div className={styles['grid']}>
        <div className={styles['field']}>
          <label htmlFor={MODEL_IDS.provider}>Provider</label>
          <select
            id={MODEL_IDS.provider}
            className={styles['select']}
            value={provider}
            onChange={(event) => {
              setProvider(event.target.value as ProviderChoice)
              setErrors({})
            }}
          >
            {view.providers.map((entry) => (
              <option key={entry.id} value={entry.id}>
                {entry.name}
              </option>
            ))}
            <option value={OTHER_ADDRESS}>Another address</option>
          </select>
        </div>
        {known ? null : (
          <div className={styles['field']}>
            <label htmlFor={MODEL_IDS.address}>Address</label>
            <input
              id={MODEL_IDS.address}
              className={styles['input']}
              type="url"
              inputMode="url"
              autoComplete="off"
              spellCheck={false}
              maxLength={2048}
              placeholder="https://"
              value={address}
              onChange={(event) => setAddress(event.target.value)}
              aria-invalid={errors.address ? true : undefined}
              aria-describedby={describedBy('model-address-help', errors.address && ERROR_IDS.address)}
            />
            <span className={styles['help']} id="model-address-help">
              An Approver must confirm a new address once before runs use it.
            </span>
            <FieldError id={ERROR_IDS.address} words={errors.address} />
          </div>
        )}
        <div className={cx(styles['field'], styles['wide'])}>
          <label htmlFor={MODEL_IDS.key}>API key</label>
          <span className={styles['keybox']}>
            <input
              ref={keyInput}
              id={MODEL_IDS.key}
              className={styles['input']}
              type={showKey ? 'text' : 'password'}
              autoComplete="off"
              autoCapitalize="off"
              autoCorrect="off"
              spellCheck={false}
              maxLength={4096}
              placeholder={view.active ? `Paste a new key to replace the one ending ${keyHint(view.active.key_hint)}` : 'Paste the key from your provider'}
              aria-invalid={errors.key ? true : undefined}
              aria-describedby={describedBy('model-key-help', errors.key && ERROR_IDS.key)}
            />
            <Button aria-controls={MODEL_IDS.key} onClick={() => setShowKey((shown) => !shown)}>
              {showKey ? 'Hide' : 'Show'}
              <span className="visually-hidden"> the key</span>
            </Button>
          </span>
          <span className={styles['help']} id="model-key-help">
            Kept encrypted. After saving, nobody can read it back, and only its last 2 characters show.
            {keepsKey && view.active ? ` Leave it empty to keep the key ending ${keyHint(view.active.key_hint)}.` : ''}
          </span>
          <FieldError id={ERROR_IDS.key} words={errors.key} />
        </div>
      </div>
      <div className={styles['buttons']}>
        <Button id={MODEL_IDS.submit} type="submit" variant="primary" loading={connect.isPending}>
          {connect.isPending ? 'Connecting' : 'Connect'}
        </Button>
      </div>
      <FieldError id={ERROR_IDS.form} words={errors.form} />
    </form>
  )
}
