import { useErrorWords } from '../../api/context'
import { isConflict } from '../../api/queries'
import { ButtonLink } from '../../ui/Button'
import { InlineMessage } from '../../ui/Feedback'
import styles from './Form.module.css'

/** A refusal because no AI model is connected, with the way to fix it. */
export function ModelNeeded({ message }: { message: string }) {
  return (
    <div className={styles['model']}>
      <InlineMessage tone="error">{message}</InlineMessage>
      <ButtonLink to="/settings">Open Settings</ButtonLink>
    </div>
  )
}

/** Any error from the platform in plain words. A 409 here means no AI model is connected, so it links to Settings. */
export function Trouble({ error }: { error: unknown }) {
  const explain = useErrorWords()
  return isConflict(error) ? <ModelNeeded message={explain(error)} /> : <InlineMessage tone="error">{explain(error)}</InlineMessage>
}
