import { Button, ButtonLink } from '../../ui/Button'
import { IconAlert, IconCheck, IconLock, IconPause, IconPlay, type Icon } from '../../ui/icons'
import { ADD_THE_YES_BACK, SAVE_AGAIN, UNDO } from './n8nChange'
import type { Banner } from './workflow'
import styles from './Workflows.module.css'

const BANNER_ICON: Record<Banner['tone'], Icon | null> = { ok: IconCheck, wait: IconLock, bad: IconAlert, off: IconPause, new: null }

type Action = NonNullable<Banner['action']>

/** The banner's actions that are the state's main one. The page draws no other primary button beside them. */
const PRIMARY: ReadonlySet<Action['kind']> = new Set(['resume', 'decide', 'yes', 'resave'])

/** The actions that sit in the page's title row, beside Change and Pause, instead of in a banner. */
export const titleRowAction = (action: Banner['action']): action is Extract<NonNullable<Banner['action']>, { kind: 'resume' | 'decide' | 'open' }> =>
  action !== null && (action.kind === 'resume' || action.kind === 'decide' || action.kind === 'open')

/**
 * Whether the banner says nothing the page does not already say. The state mark says On, Paused or Needs you, the title row holds the
 * action for a run or a pause, Next run says when, and Recent runs says how the last run went, so only what none of them says stays:
 * a refused write, a version that needs a fix, one deleted in n8n, a workflow that could not move to n8n.
 */
export function bannerRepeatsThePage(banner: Banner, useCase: { readonly state: string; readonly deleted_in_n8n_at?: string | null }): boolean {
  if (titleRowAction(banner.action) || banner.tone === 'ok') return true
  return banner.tone === 'off' && useCase.state === 'paused' && !useCase.deleted_in_n8n_at
}

export const leadsThePage =(action: Banner['action']): boolean => action !== null && PRIMARY.has(action.kind)

interface BannerViewProps {
  readonly banner: Banner
  readonly resuming: boolean
  readonly onResume: () => void
  /** Presses Add the yes back, Undo or Save the schedule again. The page asks the platform. */
  readonly onRepublish?: (action: Extract<NonNullable<Banner['action']>, { kind: 'yes' | 'undo' | 'resave' }>) => void
  readonly republishing?: boolean
}

interface ButtonProps {
  readonly action: NonNullable<Banner['action']>
  readonly resuming: boolean
  readonly onResume: () => void
  readonly onRepublish: NonNullable<BannerViewProps['onRepublish']>
  readonly republishing: boolean
}

/** A stop opens its run, as in the sketch. Retry and the troubleshooter's answers are on the run. */
function BannerButton({ action, resuming, onResume, onRepublish, republishing }: ButtonProps) {
  const variant = leadsThePage(action) ? 'primary' : 'secondary'
  switch (action.kind) {
    case 'resume':
      return (
        <Button variant={variant} icon={IconPlay} data-place="switch" loading={resuming} onClick={onResume}>
          Resume
        </Button>
      )
    case 'decide':
      return (
        <ButtonLink to={`/runs/${action.runId}`} variant={variant}>
          Review and decide
        </ButtonLink>
      )
    case 'yes':
      return (
        <Button variant={variant} loading={republishing} onClick={() => onRepublish(action)}>
          {ADD_THE_YES_BACK}
        </Button>
      )
    case 'undo':
      return (
        <Button variant={variant} loading={republishing} onClick={() => onRepublish(action)}>
          {UNDO}
        </Button>
      )
    case 'resave':
      return (
        <Button variant={variant} loading={republishing} onClick={() => onRepublish(action)}>
          {SAVE_AGAIN}
        </Button>
      )
    case 'open':
      return (
        <ButtonLink to={`/runs/${action.runId}`} variant={variant}>
          Open the run
        </ButtonLink>
      )
  }
}

/** One sentence on the state and the one action that moves it on. The tone is also in the words, never in colour alone. */
export function StatusBanner({ banner, resuming, onResume, onRepublish = () => undefined, republishing = false }: BannerViewProps) {
  const Mark = BANNER_ICON[banner.tone]
  const { action } = banner
  return (
    <div className={styles['banner']} data-tone={banner.tone}>
      <span className={styles['bannerMark']}>{Mark ? <Mark size={20} /> : null}</span>
      <p>{banner.text}</p>
      {action ? <BannerButton action={action} resuming={resuming} onResume={onResume} onRepublish={onRepublish} republishing={republishing} /> : null}
    </div>
  )
}
