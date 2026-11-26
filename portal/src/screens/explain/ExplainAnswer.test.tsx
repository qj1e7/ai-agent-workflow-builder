import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import turnedOn from '../../../../contracts/fixtures/builder/use-case.turned-on.json'
import explainOne from '../../../../contracts/fixtures/planner/answer.explain.json'
import explainSeveral from '../../../../contracts/fixtures/planner/answer.explain.choices.json'
import explainMissing from '../../../../contracts/fixtures/planner/answer.explain.missing.json'
import explainIt from '../../../../contracts/fixtures/planner/answer.explain.it.json'
import { ApiError } from '../../api/client'
import { ApiProvider } from '../../api/context'
import { keys } from '../../api/queries'
import { createDevSession } from '../../api/session'
import type { ExplainReply, UseCaseView } from '../../api/types'
import type { Page } from '../home/AnswerCards'
import { CardMemoryContext, newCardMemory, NO_MEMORY, type CardMemory } from '../home/cardMemory'
import { sayOf, wordsOnly } from '../home/answers'
import { leftoverParts } from '../home/parts'
import { sentenceOf } from '../workflows/workflow'
import { ExplainAnswer, MOST_WHICH } from './ExplainAnswer'

const PAGE: Page = { ask: () => undefined, edit: () => undefined, box: () => undefined }
const ONE = explainOne as ExplainReply
const SEVERAL = explainSeveral as ExplainReply
const IT = explainIt as ExplainReply
const MISSING = explainMissing as ExplainReply
const FASTAPI = 'uc_01JFASTAPI'
const REACT = 'uc_01JB8'

const LANGGRAPH = turnedOn as UseCaseView
/** The FastAPI release check as its page reads it: the turned-on release check, watching fastapi/fastapi. */
const FASTAPI_VIEW: UseCaseView = {
  ...LANGGRAPH,
  use_case_id: FASTAPI,
  name: 'FastAPI release check',
  agents: LANGGRAPH.agents.map((agent) => ({ ...agent, values: { ...agent.values, 'GitHub repository': 'fastapi/fastapi' } })),
}

interface Drawn {
  readonly focus?: string | null
  /** The workflows the Portal has read, as their pages read them. */
  readonly held?: readonly UseCaseView[]
  /** A workflow whose read failed, with how. */
  readonly failed?: { readonly id: string; readonly error: Error }
  readonly memory?: CardMemory
}

function draw(reply: ExplainReply, { focus = null, held = [], failed, memory = NO_MEMORY }: Drawn = {}): string {
  const session = createDevSession(null)
  const scope = session.cacheScope()
  const queryClient = new QueryClient({ defaultOptions: { queries: { retryOnMount: false } } })
  for (const view of held) queryClient.setQueryData(keys.useCase(scope, view.use_case_id), view)
  if (failed) queryClient.getQueryCache().build(queryClient, { queryKey: keys.useCase(scope, failed.id) }).setState({ status: 'error', error: failed.error, fetchStatus: 'idle' })
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
const paragraphs = (html: string) => [...html.matchAll(/<p\b[^>]*>([\s\S]*?)<\/p>/g)].map((m) => text(m[1] ?? ''))

const FASTAPI_SAYS = 'Every Monday at 8:00, check fastapi/fastapi on GitHub for a new release. If there is one, create an upgrade ticket in Jira project MOCK, after approval.'

describe('the Explain answer in the chat', () => {
  it('says nothing above its card, drawn as cards and not as words, with no part dropped', () => {
    expect(sayOf(ONE)).toBeNull()
    expect(wordsOnly(ONE, 'operator')).toBe(false)
    expect(leftoverParts(ONE)).toEqual([])
    expect(leftoverParts({ ...ONE, parts: [{ text: 'and add Redis', mark: 'cant', reason: 'cant_do', note: null, choices: [] }] })).toHaveLength(1)
  })

  describe('one workflow named', () => {
    it('shows a short line while the workflow loads, under its name, with nothing yet to open', () => {
      const html = draw(ONE)
      expect(title(html)).toBe('FastAPI release check')
      expect(text(html)).toContain('Loading the workflow')
      expect(buttons(html)).toEqual([])
    })

    it('answers with the sentence the workflow’s page shows, and one button to open that page', () => {
      const html = draw(ONE, { held: [FASTAPI_VIEW] })
      expect(title(html)).toBe('FastAPI release check')
      expect(paragraphs(html)).toEqual([sentenceOf(FASTAPI_VIEW)])
      expect(sentenceOf(FASTAPI_VIEW)).toBe(FASTAPI_SAYS)
      expect(buttons(html)).toEqual(['Open the workflow'])
      expect(html).toContain('href="/workflows/uc_01JFASTAPI"')
    })

    it('shows no report: no sections, no reworded wording and nothing to swap', () => {
      const html = draw(ONE, { held: [FASTAPI_VIEW] })
      expect(text(html)).not.toMatch(/Step by step|Reworded|Code’s wording|Flags|Who approves each write/)
      expect(html).not.toContain('<details')
    })

    it('keeps the Operator’s own words for a workflow that isn’t a release check, as its page does', () => {
      const own: UseCaseView = { ...FASTAPI_VIEW, agents: [], instruction: 'Post the closed bugs to the team every Friday.' }
      const html = draw(ONE, { held: [own] })
      expect(paragraphs(html)).toEqual(['Post the closed bugs to the team every Friday.'])
    })

    it('says a workflow deleted since is not there, with nothing to open', () => {
      const html = draw(ONE, { failed: { id: FASTAPI, error: new ApiError(404, { detail: 'No such use case' }) } })
      expect(title(html)).toBe('FastAPI release check')
      expect(text(html)).toContain('That workflow isn’t here any more.')
      expect(buttons(html)).toEqual([])
    })

    it('says so when the workflow could not be loaded, with Try again', () => {
      const html = draw(ONE, { failed: { id: FASTAPI, error: new ApiError(503, null) } })
      expect(text(html)).toContain('The workflow could not be loaded.')
      expect(html).toContain('role="alert"')
      expect(buttons(html)).toEqual(['Try again'])
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
    it('explains the workflow in focus with its page’s sentence, by the name its choices carry', () => {
      const html = draw(IT, { focus: FASTAPI, held: [FASTAPI_VIEW] })
      expect(title(html)).toBe('FastAPI release check')
      expect(paragraphs(html)).toEqual([FASTAPI_SAYS])
      expect(buttons(html)).toEqual(['Open the workflow'])
    })

    it('asks which workflow when none is in focus', () => {
      const html = draw(IT, { focus: null })
      expect(title(html)).toBe('Which workflow?')
      expect(buttons(html)).toEqual(['FastAPI release check', 'React release check'])
    })

    it('keeps the workflow it explained when the focus changes later, so the card in the chat stays', () => {
      const memory = newCardMemory()
      draw(IT, { focus: FASTAPI, held: [FASTAPI_VIEW], memory })
      const later = draw(IT, { focus: REACT, held: [FASTAPI_VIEW], memory })
      expect(title(later)).toBe('FastAPI release check')
    })

    it('keeps asking which when it asked, even if the panel shows a workflow later', () => {
      const memory = newCardMemory()
      draw(IT, { focus: null, memory })
      expect(title(draw(IT, { focus: REACT, memory }))).toBe('Which workflow?')
    })
  })
})
