import type { ReactElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import approval from '../../../../contracts/fixtures/builder/setup-approval.bob.json'
import type { ExplainFlag, WorkflowExplained } from '../../api/types'
import { Checks, Flag, Settings, Touches, WhoApproves, Words } from './Report'

const REPORT = approval.report as WorkflowExplained

const decoded = (html: string) => html.replace(/&#x27;/g, '’').replace(/&quot;/g, '"').replace(/&amp;/g, '&')
const text = (part: ReactElement) => decoded(renderToStaticMarkup(part).replace(/<[^>]*>/g, ' ')).replace(/\s+/g, ' ').trim()

describe('the parts of a workflow’s report the set-up approval and the drafted card draw', () => {
  it('shows every quoted value in curly quotes, styled apart from code’s words', () => {
    const html = renderToStaticMarkup(<Words segments={[{ text: 'reads GitHub ', quoted: false }, { text: 'langchain-ai/langgraph', quoted: true }]} />)
    expect(html).toMatch(/^reads GitHub <span class="[^"]*quoted[^"]*">“langchain-ai\/langgraph”<\/span>$/)
  })

  it('lists what it reads, writes and posts with the block that does it, and says when it touches nothing', () => {
    const said = text(<Touches touches={REPORT.touches} />)
    expect(said).toContain('Reads GitHub “langchain-ai/langgraph” By “Read new releases”')
    expect(said).toContain('Writes Jira “MOCK” By “Make the ticket”')
    expect(text(<Touches touches={[]} />)).toBe('It reads, writes and posts nothing.')
  })

  it('says who decides each write, and that a workflow that writes nothing needs nobody', () => {
    expect(text(<WhoApproves approves={REPORT.approves} />)).toBe('“Make the ticket” Waits for an Approver in Teams on each run. Nobody who started the run or made the workflow can approve it.')
    expect(text(<WhoApproves approves={[]} />)).toBe('It writes nothing, so nobody approves a write.')
  })

  it('draws a setting’s label and value as segments, with where it was set, and a needed one as not given yet', () => {
    const settings = REPORT.settings
    expect(text(<Settings settings={settings} />)).toContain('“The repository” “langchain-ai/langgraph” From your words')
    const needed = [{ ...settings[0]!, value: null, mark: 'needed' as const, said: 'Needed' }]
    expect(text(<Settings settings={needed} />)).toContain('Not given yet')
  })

  it('lists a flag with where, why and who clears it', () => {
    const flag: ExplainFlag = { rule: 'no_error_workflow', block: 'Make the ticket', what: 'A stopped run isn’t reported', why: 'It has no error workflow.', clears: 'cant_run', takes: 'Fix it in n8n.' }
    const said = text(<Flag flag={flag} />)
    expect(said.startsWith('A stopped run isn’t reported In “Make the ticket”')).toBe(true)
    expect(said.endsWith('It has no error workflow. Fix it in n8n.')).toBe(true)
  })

  it('lists what code fixed, then what passed, and leaves out a list with nothing in it', () => {
    const said = text(<Checks report={REPORT} />)
    expect(said.indexOf('Fixed for you')).toBeLessThan(said.indexOf('Passed'))
    expect(said).toContain('Set the team’s time zone.')
    expect(said).toContain('Every block loads in our n8n.')
    expect(text(<Checks report={{ fixed: [], passed: REPORT.passed }} />)).not.toContain('Fixed for you')
  })
})
