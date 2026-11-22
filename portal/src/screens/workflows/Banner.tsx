import { Button, ButtonLink } from '../../ui/Button'
import { IconAlert, IconCheck, IconLock, IconPause, IconPlay, type Icon } from '../../ui/icons'
import { explainFlagsPath } from '../explain/explain'
import { ADD_THE_YES_BACK, SAVE_AGAIN, UNDO } from './n8nChange'
import type { Banner } from './workflow'
import styles from './Workflows.module.css'

const BANNER_ICON: Record<Banner['tone'], Icon | null> = { ok: IconCheck, wait: IconLock, bad: IconAlert, off: IconPause, new: null }

type Action = NonNullable<Banner['action']>

/** The banner's actions that are the state's main one. The page draws no other primary button beside them. */
const PRIMARY: ReadonlySet<Action['kind']> = new Set(['resume', 'decide', 'yes', 'resave'])

export const leadsThePage = (action: Banner['action']): boolean => action !== null && PRIMARY.has(action.kind)

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
    case 'explain':
      return (
        <ButtonLink to={explainFlagsPath(action.useCaseId)} variant={variant}>
          Explain
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
