import { useId } from 'react'
import { useModelOff } from '../../api/queries'
import { Button, ButtonLink } from '../../ui/Button'
import { IconAlert, IconCheck, IconLock, IconPause, IconPlay, type Icon } from '../../ui/icons'
import { stoppedActions } from '../home/home'
import { RetryButton } from '../home/HomeItem'
import type { Banner } from './workflow'
import styles from './Workflows.module.css'

const BANNER_ICON: Record<Banner['tone'], Icon | null> = { ok: IconCheck, wait: IconLock, bad: IconAlert, off: IconPause, new: null }

interface BannerViewProps {
  readonly banner: Banner
  readonly resuming: boolean
  readonly onResume: () => void
}

interface ButtonProps {
  readonly action: NonNullable<Banner['action']>
  readonly resuming: boolean
  readonly onResume: () => void
  readonly describedBy: string
}

function BannerButton({ action, resuming, onResume, describedBy }: ButtonProps) {
  const modelOff = useModelOff()
  switch (action.kind) {
    case 'resume':
      return (
        <Button variant="primary" icon={IconPlay} data-place="switch" loading={resuming} onClick={onResume}>
          Resume
        </Button>
      )
    case 'decide':
      return (
        <ButtonLink to={`/runs/${action.runId}`} variant="primary">
          Review and decide
        </ButtonLink>
      )
    case 'open':
      return <ButtonLink to={`/runs/${action.runId}`}>Open the run</ButtonLink>
    case 'stopped': {
      const [first] = stoppedActions(action.runId, action.retryable, modelOff)
      if (first?.kind === 'retry') return <RetryButton runId={first.runId} label={first.label} primary describedBy={describedBy} />
      return (
        <ButtonLink to={`/runs/${action.runId}`} variant="primary">
          {first?.kind === 'open' ? first.label : 'See why it stopped'}
        </ButtonLink>
      )
    }
  }
}

/** One sentence on the state and the one action that moves it on. The tone is also in the words, never in colour alone. */
export function StatusBanner({ banner, resuming, onResume }: BannerViewProps) {
  const Mark = BANNER_ICON[banner.tone]
  const { action } = banner
  const textId = useId()
  return (
    <div className={styles['banner']} data-tone={banner.tone}>
      <span className={styles['bannerMark']}>{Mark ? <Mark size={20} /> : null}</span>
      <p id={textId}>{banner.text}</p>
      {action ? <BannerButton action={action} resuming={resuming} onResume={onResume} describedBy={textId} /> : null}
    </div>
  )
}

