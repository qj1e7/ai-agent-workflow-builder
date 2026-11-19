import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import current from '../../../../contracts/fixtures/builder/explain.json'
import reworded from '../../../../contracts/fixtures/builder/explain.reworded.json'
import explainOne from '../../../../contracts/fixtures/planner/answer.explain.json'
import explainSeveral from '../../../../contracts/fixtures/planner/answer.explain.choices.json'
import explainMissing from '../../../../contracts/fixtures/planner/answer.explain.missing.json'
import explainIt from '../../../../contracts/fixtures/planner/answer.explain.it.json'
import { ApiProvider } from '../../api/context'
import { createDevSession } from '../../api/session'
import type { ExplainReply, WorkflowExplained } from '../../api/types'
import type { Page } from '../home/AnswerCards'
import { CardMemoryContext, newCardMemory, NO_MEMORY, type CardMemory } from '../home/cardMemory'
import { sayOf, wordsOnly } from '../home/answers'
import { leftoverParts } from '../home/parts'
import { ExplainAnswer, MOST_WHICH } from './ExplainAnswer'

const PAGE: Page = { ask: () => undefined, edit: () => undefined, box: () => undefined }
const ONE = explainOne as ExplainReply
const SEVERAL = explainSeveral as ExplainReply
const IT = explainIt as ExplainReply
const MISSING = explainMissing as ExplainReply
const FASTAPI = 'uc_01JFASTAPI'
const REACT = 'uc_01JB8'

interface Held {
  readonly id: string
  readonly report: WorkflowExplained
}

function draw(reply: ExplainReply, { focus = null, held = [], memory = NO_MEMORY }: { focus?: string | null; held?: readonly Held[]; memory?: CardMemory } = {}): string {
  const session = createDevSession(null)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retryOnMount: false } } })
  for (const { id, report } of held) queryClient.setQueryData(['use-case', session.cacheScope(), id, 'explain', null, true], report)
  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <ApiProvider session={session} platformFetch={fetch} origin="http://portal.test">
        <MemoryRouter>
          <CardMemoryContext.Provider value={memory}>
            <ExplainAnswer reply={reply} focus={focus} page={PAGE} />
          </CardMemoryContext.Provider>
        </MemoryRouter>
      </ApiProvider>
    </QueryClientProvider>,
  )
}

const text = (html: string) => html.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim()
const buttons = (html: string) => [...html.matchAll(/<(?:button|a)\b[^>]*>([\s\S]*?)<\/(?:button|a)>/g)].map((m) => text(m[1] ?? ''))
const title = (html: string) => text(/<h3\b[^>]*>([\s\S]*?)<\/h3>/.exec(html)?.[1] ?? '')
const short = (html: string) => (/<p class="[^"]*short[^"]*"[^>]*>([\s\S]*?)<\/p>/.exec(html)?.[1] ?? '').replace(/<[^>]*>/g, '')

const PLAIN: Held = { id: FASTAPI, report: current as WorkflowExplained }
const SMOOTH: Held = { id: FASTAPI, report: reworded as WorkflowExplained }

describe('the Explain answer in the chat', () => {
  it('says nothing above its card, drawn as cards and not as words, with no part dropped', () => {
    expect(sayOf(ONE)).toBeNull()
    expect(wordsOnly(ONE, 'operator')).toBe(false)
    expect(leftoverParts(ONE)).toEqual([])
    expect(leftoverParts({ ...ONE, parts: [{ text: 'and add Redis', mark: 'cant', reason: 'cant_do', note: null, choices: [] }] })).toHaveLength(1)
  })

  describe('one workflow named', () => {
    it('shows a short line while the report comes, under the workflow’s name, with nothing yet to open', () => {
      const html = draw(ONE)
      expect(title(html)).toBe('FastAPI release check')
      expect(text(html)).toContain('Reading the workflow')
      expect(buttons(html)).toEqual([])
    })

    it('shows the report under the workflow’s name, with Open the workflow, once it came', () => {
      const html = draw(ONE, { held: [PLAIN] })
      expect(title(html)).toBe('FastAPI release check')
      expect(short(html)).toContain('Every day at 8:00, it reads GitHub')
      expect(text(html)).toContain('Step by step 8 blocks')
      expect(buttons(html)).toEqual(['Open the workflow'])
      expect(html).toContain('href="/workflows/uc_01JFASTAPI"')
    })

    it('shows the reworded In short with the pill Reworded and a button to code’s wording, the sections in code’s words', () => {
      const html = draw(ONE, { held: [SMOOTH] })
      expect(short(html)).toBe('Every day at 8:00, it reads GitHub “fastapi/fastapi” and Jira “MOCK”. It can create Jira tickets in “MOCK”, each after a yes, and changes nothing else.')
      expect(text(html)).toContain('Reworded')
      expect(buttons(html)).toEqual(['Show code’s wording', 'Open the workflow'])
      expect(text(html)).toContain('Writes after a yes')
    })

    it('shows code’s wording with the pill Code’s wording after the swap, and the swap stays when Home comes back', () => {
      const memory = newCardMemory()
      memory.wording.keep(true)
      const html = draw(ONE, { held: [SMOOTH], memory })
      expect(short(html)).toContain('It changes nothing else.')
      expect(text(html)).toContain('Code’s wording')
      expect(buttons(html)).toEqual(['Show the reworded one', 'Open the workflow'])
    })

    it('shows code’s wording with no pill when nothing came reworded, as for a workflow that reads facebook/react', () => {
      const html = draw(ONE, { held: [PLAIN] })
      expect(text(html)).not.toMatch(/Reworded|Code’s wording/)
      expect(buttons(html).filter((label) => label.includes('wording'))).toEqual([])
    })
  })

  describe('several workflows matched', () => {
    it('asks Which workflow? with a button for each', () => {
      const html = draw(SEVERAL)
      expect(title(html)).toBe('Which workflow?')
      expect(buttons(html)).toEqual(['FastAPI release check', 'React release check'])
    })

    it('counts the choices past the most it lists, with a way to the rest', () => {
      const many = { ...SEVERAL, choices: Array.from({ length: MOST_WHICH + 3 }, (_, n) => ({ use_case_id: `uc_${String(n)}`, name: `Check ${String(n)}` })) }
      const html = draw(many)
      expect(buttons(html)).toHaveLength(MOST_WHICH + 1)
      expect(buttons(html).at(-1)).toBe('and 3 more')
      expect(html).toContain('href="/workflows"')
    })
  })

  describe('words that match nothing', () => {
    it('says it can’t find the workflow, what it looked for, and offers Check my workflows', () => {
      const html = draw(MISSING)
      expect(title(html)).toBe('I can’t find a workflow called that.')
      expect(text(html)).toContain('I looked for “Kubernetes check”.')
      expect(buttons(html)).toEqual(['Check my workflows'])
      expect(html).toContain('href="/workflows"')
    })
  })

  describe('“explain it”', () => {
    it('explains the workflow in focus, by the name its choices carry', () => {
      const html = draw(IT, { focus: FASTAPI, held: [PLAIN] })
      expect(title(html)).toBe('FastAPI release check')
      expect(buttons(html)).toEqual(['Open the workflow'])
    })

    it('asks which workflow when none is in focus', () => {
      const html = draw(IT, { focus: null })
      expect(title(html)).toBe('Which workflow?')
      expect(buttons(html)).toEqual(['FastAPI release check', 'React release check'])
    })

    it('keeps the workflow it explained when the focus changes later, so the card in the chat stays', () => {
      const memory = newCardMemory()
      draw(IT, { focus: FASTAPI, held: [PLAIN], memory })
      const later = draw(IT, { focus: REACT, held: [PLAIN], memory })
      expect(title(later)).toBe('FastAPI release check')
    })

    it('keeps asking which when it asked, even if the panel shows a workflow later', () => {
      const memory = newCardMemory()
      draw(IT, { focus: null, memory })
      expect(title(draw(IT, { focus: REACT, memory }))).toBe('Which workflow?')
    })
  })
})
