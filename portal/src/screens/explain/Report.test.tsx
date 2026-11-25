import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import current from '../../../../contracts/fixtures/builder/explain.json'
import older from '../../../../contracts/fixtures/builder/explain.older.json'
import reworded from '../../../../contracts/fixtures/builder/explain.reworded.json'
import type { WorkflowExplained } from '../../api/types'
import { Report } from './Report'

const REPORT = current as WorkflowExplained
const OLDER = older as WorkflowExplained
const REWORDED = reworded as WorkflowExplained

const decoded = (html: string) => html.replace(/&#x27;/g, '’').replace(/&quot;/g, '"').replace(/&amp;/g, '&')
const text = (html: string) => decoded(html.replace(/<[^>]*>/g, ' ')).replace(/\s+/g, ' ').trim()
const short = (html: string) => decoded(/<p class="[^"]*short[^"]*"[^>]*>([\s\S]*?)<\/p>/.exec(html)?.[1] ?? '').replace(/<[^>]*>/g, '')
const titles = (html: string) => [...html.matchAll(/<summary[^>]*><span[^>]*>([^<]*)<\/span><span[^>]*>([^<]*)<\/span><\/summary>/g)].map((m) => [m[1], m[2]])
const buttons = (html: string) => [...html.matchAll(/<button\b[^>]*>([\s\S]*?)<\/button>/g)].map((m) => text(m[1] ?? ''))
const draw = (report: WorkflowExplained, props: { code?: boolean; onWording?: () => void } = {}) => renderToStaticMarkup(<Report report={report} {...props} />)

describe('the report, as layout B draws it', () => {
  it('leads with In short, in code’s words, then one row per section with its gist', () => {
    const html = draw(REPORT)
    expect(html.indexOf('Every day at 8:00')).toBeLessThan(html.indexOf('<summary'))
    expect(titles(html)).toEqual([
      ['Step by step', '8 blocks'],
      ['What it reads, writes and posts', 'Reads GitHub and Jira · Writes Jira'],
      ['Flags', `${REPORT.fixed.length} fixed for you · ${REPORT.passed.length} passed`],
      ['Who approves each write', '1 waits for approval on each run'],
      ['Settings', `${REPORT.settings.length} settings`],
      ['Approval', 'None needed'],
    ])
    expect(short(html)).toBe('Every day at 8:00, it reads GitHub “fastapi/fastapi” and Jira “MOCK”. It can create Jira tickets in “MOCK”, each after a yes. It changes nothing else.')
  })

  it('draws each row as a disclosure a click or the keyboard opens, closed to begin with', () => {
    const html = draw(REPORT)
    expect(html.match(/<details/g)).toHaveLength(6)
    expect(html.match(/<summary/g)).toHaveLength(6)
    expect(html).not.toMatch(/<details[^>]* open/)
  })

  it('opens Settings by itself while an answer is needed, and only Settings', () => {
    const needed = { ...REPORT, needs_an_answer: 1, settings: [{ ...REPORT.settings[0]!, mark: 'needed' as const, value: null, said: 'Not given yet' }] }
    const html = draw(needed)
    const open = [...html.matchAll(/<details[^>]* open[^>]*>\s*<summary[^>]*><span[^>]*>([^<]*)</g)].map((m) => m[1])
    expect(open).toEqual(['Settings'])
    expect(titles(html).find(([title]) => title === 'Settings')?.[1]).toBe('1 needed')
    expect(text(html)).toContain('Not given yet')
  })

  it('shows every quoted value in curly quotes, styled apart from code’s words', () => {
    const html = draw(REPORT)
    expect(html).toMatch(/<span class="[^"]*quoted[^"]*">“fastapi\/fastapi”<\/span>/)
    expect(html).toMatch(/<span class="[^"]*quoted[^"]*">“Read release”<\/span>/)
    expect(html).not.toMatch(/<span class="[^"]*quoted[^"]*">(?!“)/)
    expect(html).not.toMatch(/<span class="[^"]*quoted[^"]*">“[^<]*[^”]<\/span>/)
  })

  it('draws a setting’s label and value as segments too, with where it was set', () => {
    const body = text(draw(REPORT))
    expect(body).toContain('Where “Read release” reads')
    expect(body).toContain('Set in the Portal')
  })

  it('leaves block types and the n8n badge out when no block has one', () => {
    const html = text(draw(REPORT))
    expect(html).toContain('Reads GitHub')
    expect(html).not.toMatch(/· (?:our|n8n) block,/)
  })

  it('shows a block’s type, and whether it is ours or n8n’s, only where the platform sent one', () => {
    const typed = { ...REPORT, steps: REPORT.steps.map((step, index) => (index === 2 ? { ...step, block_type: 'platform.read_release' } : index === 4 ? { ...step, block_type: 'n8n-nodes-base.if' } : step)) }
    const html = text(draw(typed))
    expect(html).toContain('Reads GitHub · our block, platform.read_release')
    expect(html).toContain('Shapes the data · n8n block, n8n-nodes-base.if')
    expect(html.match(/· (?:our|n8n) block,/g)).toHaveLength(2)
  })

  it('lists what it reads, writes and posts with the block that does it', () => {
    const html = text(draw(REPORT))
    expect(html).toContain('Reads GitHub “fastapi/fastapi” By “Read release”')
    expect(html).toContain('Writes Jira “MOCK” By “Create ticket”')
  })

  it('says who decides each write, and that a workflow that writes nothing needs nobody', () => {
    expect(text(draw(REPORT))).toContain('“Create ticket” Waits for an Approver in Teams on each run. Nobody who started the run or made the workflow can approve it.')
    expect(text(draw({ ...REPORT, approves: [] }))).toContain('It writes nothing, so nobody approves a write.')
  })

  it('lists each flag with why and who clears it, then what was fixed and what passed', () => {
    const html = text(draw(OLDER))
    expect(html).toContain('A stopped run isn’t reported')
    expect(html).toContain('Fix it in n8n. Code makes sure of it in every workflow it lays out.')
    expect(html).toContain('Fixed for you')
    expect(html).toContain('Set the team’s time zone.')
    expect(html).toContain('Passed')
    expect(html).toContain('Every block loads in our n8n.')
    expect(text(draw(REPORT))).toContain('No flags.')
  })
})

describe('an older version', () => {
  it('says which version it is, that today’s rules checked it again, and the grade it had then', () => {
    const html = text(draw(OLDER))
    expect(html).toContain('Version 1. Checked again under today’s rules.')
    expect(html).toContain('Graded Safe when it was published, and Needs a fix today.')
  })

  it('says nothing of the sort for the version in use', () => {
    expect(text(draw(REPORT))).not.toContain('Checked again')
  })
})

describe('Reworded and code’s wording', () => {
  it('shows In short in code’s words, with no label and no button, when nothing was reworded', () => {
    const html = draw(REPORT, { onWording: () => undefined })
    expect(buttons(html).filter((label) => /wording|reworded/i.test(label))).toEqual([])
    expect(text(html)).not.toContain('Reworded')
  })

  it('shows the reworded In short with the pill Reworded and a button back to code’s wording', () => {
    const html = draw(REWORDED, { onWording: () => undefined })
    expect(short(html)).toBe('Every day at 8:00, it reads GitHub “fastapi/fastapi” and Jira “MOCK”. It can create Jira tickets in “MOCK”, each after a yes, and changes nothing else.')
    expect(html).toMatch(/<span class="[^"]*label[^"]*">Reworded<\/span>/)
    expect(buttons(html)).toEqual(['Show code’s wording'])
  })

  it('swaps to code’s own words with the pill Code’s wording and a button to the reworded one', () => {
    const html = draw(REWORDED, { code: true, onWording: () => undefined })
    expect(short(html)).toContain('It changes nothing else.')
    expect(html).toMatch(/<span class="[^"]*label[^"]*">Code’s wording<\/span>/)
    expect(buttons(html)).toEqual(['Show the reworded one'])
  })

  it('keeps every section in code’s words either way', () => {
    const sections = (html: string) => html.slice(html.indexOf('<details'))
    expect(sections(draw(REWORDED, { onWording: () => undefined }))).toBe(sections(draw(REWORDED, { code: true, onWording: () => undefined })))
  })
})
