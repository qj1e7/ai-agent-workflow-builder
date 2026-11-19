import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import current from '../../../../contracts/fixtures/builder/explain.json'
import type { WorkflowExplained } from '../../api/types'
import { Explained } from './Explained'
import type { ExplainState } from './explain'

const text = (html: string) => html.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim()
const buttons = (html: string) => [...html.matchAll(/<button\b[^>]*>([\s\S]*?)<\/button>/g)].map((m) => text(m[1] ?? ''))
const draw = (state: ExplainState) => renderToStaticMarkup(<Explained state={state} retry={() => undefined}>{(report) => <p>Report of {report.name}</p>}</Explained>)

describe('the report where it loads', () => {
  it('draws the report when it came', () => {
    expect(text(draw({ kind: 'report', report: current as WorkflowExplained }))).toBe('Report of FastAPI release check')
  })

  it('says it is reading while it waits, with nothing to press', () => {
    const html = draw({ kind: 'loading' })
    expect(text(html)).toBe('Reading the workflow')
    expect(html).toContain('role="status"')
    expect(buttons(html)).toEqual([])
  })

  it('puts the server’s words where the report would be, with nothing to press', () => {
    const html = draw({ kind: 'said', words: 'Nothing to explain: this version ran on the shared n8n workflow, so the platform kept no copy of its blocks.' })
    expect(text(html)).toBe('Nothing to explain: this version ran on the shared n8n workflow, so the platform kept no copy of its blocks.')
    expect(buttons(html)).toEqual([])
  })

  it('gives the reason and Try again when the load failed, and the button is not disabled', () => {
    const html = draw({ kind: 'failed' })
    expect(text(html)).toContain('The report could not be loaded.')
    expect(html).toContain('role="alert"')
    expect(buttons(html)).toEqual(['Try again'])
    expect(html).not.toMatch(/<button[^>]*(?<!aria-)disabled=/)
  })
})
