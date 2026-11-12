import { MessageBox } from './MessageBox'
import { ANSWER_HELP, EMPTY_ANSWER } from './questions'

interface AnswerQuestionProps {
  /** Who asked, by name. */
  readonly askedBy: string
  readonly pending: boolean
  /** What the platform said about this person's last answer to this question. */
  readonly error: string | null
  readonly onAnswer: (text: string) => void
}

/** The requester's answer box, under the question on the request, opened from Needs you. An answer decides nothing, and says so. */
export function AnswerQuestion({ askedBy, pending, error, onAnswer }: AnswerQuestionProps) {
  return <MessageBox label={`Your answer for ${askedBy}`} help={ANSWER_HELP} empty={EMPTY_ANSWER} send="Send answer" pending={pending} error={error} onSend={onAnswer} />
}
