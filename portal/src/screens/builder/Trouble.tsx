import { Link } from 'react-router'
import { useErrorWords } from '../../api/context'
import { isConflict } from '../../api/queries'
import { InlineMessage } from '../../ui/Feedback'

/** A refusal because no AI model is connected, with the way to fix it. */
export function ModelNeeded({ message }: { message: string }) {
  return (
    <InlineMessage tone="error">
      {message} <Link to="/settings">Open Settings</Link>
    </InlineMessage>
  )
}

/** Any error from the platform in plain words. A 409 here means no AI model is connected, so it links to Settings. */
export function Trouble({ error }: { error: unknown }) {
  const explain = useErrorWords()
  return isConflict(error) ? <ModelNeeded message={explain(error)} /> : <InlineMessage tone="error">{explain(error)}</InlineMessage>
}
