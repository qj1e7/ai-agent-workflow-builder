import { OpenButton } from '../../ui/OpenItem'
import { explainPath } from './explain'

interface ExplainButtonProps {
  readonly useCaseId: string
  readonly name: string
  /** One version of it, from Versions. Leave out for the version in use. */
  readonly version?: number
}

/** Opens the report beside the chat, and as its page from anywhere else. Both roles see it: explaining changes nothing. */
export function ExplainButton({ useCaseId, name, version }: ExplainButtonProps) {
  const shown = version ?? null
  return (
    <OpenButton item={{ kind: 'explain', id: useCaseId, version: shown }} to={explainPath(useCaseId, shown)}>
      Explain<span className="visually-hidden"> {shown === null ? name : `${name}, version ${String(shown)}`}</span>
    </OpenButton>
  )
}
