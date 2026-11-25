import type { MadeInN8nView } from '../../api/madeInN8nQueries'
import { andList } from '../run/words'
import { gradePill, needsFixBanner } from './n8nChange'

export interface MadeInN8nWords {
  readonly line: string
  readonly sub: string
  readonly pill: { readonly label: string; readonly tone: 'ok' | 'bad' }
}

function gradeSentence({ grade, findings }: Pick<MadeInN8nView, 'grade' | 'findings'>): string {
  switch (grade) {
    case 'safe':
      return 'Safe: every change waits for approval.'
    case 'writes_refused':
      return `Writes refused: ${findings.length > 0 ? findings.join(' ') : 'a change can run without approval.'}`
    case 'needs_a_fix':
      return needsFixBanner(findings)
  }
}

const fixedWords = ({ fixed_for_you }: Pick<MadeInN8nView, 'fixed_for_you'>): string => (fixed_for_you.length > 0 ? `Set up also ${andList(fixed_for_you)}.` : '')

/** A workflow made in n8n that waits to be set up, in the plan's words (ENGINE-PLAN section 1, row 14): who made it, its grade, and what setting it up does or why it can't yet. */
export function madeInN8nWords(workflow: MadeInN8nView, makerName: string): MadeInN8nWords {
  const after = workflow.why_not ?? (workflow.published ? 'Published in n8n, so it runs once set up.' : 'It is set up as a draft, since it isn’t published in n8n.')
  const { label, tone } = gradePill(workflow.grade)
  return {
    line: 'is in n8n but not registered',
    sub: [`Made in n8n by ${makerName}.`, gradeSentence(workflow), fixedWords(workflow), ...workflow.set_up_notes, after].filter(Boolean).join(' '),
    pill: { label, tone: tone === 'ok' ? 'ok' : 'bad' },
  }
}
