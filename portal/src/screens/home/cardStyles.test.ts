/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

// Vitest blanks a CSS import, even with ?raw, so the sheets are read as files.
const SHEETS = ['../../ui/Card.module.css', './SetupCard.module.css', './EditCard.module.css', './PartsList.module.css', './StateAnswers.module.css', '../drafted/Drafted.module.css']

/** The card bodies in Planner.module.css, which also holds the chat's own layout (another change owns that). */
const PLANNER_CARD = ['lines', 'caps', 'steps', 'moreChoices', 'note', 'buttons', 'ask', 'sent', 'starters', 'starter', 'more', 'lookedAt', 'actions', 'cardDone', 'cardOk', 'waiting', 'chips', 'problem']

const strip = (css: string) => css.replace(/\/\*[\s\S]*?\*\//g, '')

function rules(css: string): { selector: string; body: string }[] {
  return [...strip(css).matchAll(/([^{}]+)\{([^{}]*)\}/g)].map((match) => ({ selector: (match[1] ?? '').trim(), body: match[2] ?? '' }))
}

const planner = rules(readFileSync(new URL('./Planner.module.css', import.meta.url), 'utf8'))
  .filter((rule) => rule.selector.split(',').every((selector) => PLANNER_CARD.includes(/^\s*\.([a-zA-Z]+)/.exec(selector)?.[1] ?? '')))
  .map((rule) => `${rule.selector}{${rule.body}}`)
  .join('\n')

const sheets = [...SHEETS.map((file) => ({ file, css: strip(readFileSync(new URL(file, import.meta.url), 'utf8')) })), { file: './Planner.module.css (card rules)', css: planner }]

/** The card surfaces: the one card, the left-out words above a card and a starter. Each may have a shadow, and nothing inside them may. */
const SURFACES = ['.card', '.leftovers', '.starter']

/** The controls that keep an edge: a chip, a choice, a field and the spinner, by exact selector. A focus or hover state is always allowed. */
const EDGED = new Set(['.chip', 'button.chip', '.choice', '.value', '.editor input', '.editor select', '.field input', '.field select', '.another input', '.input', '.spin', '.ask textarea'])

const RAW_LENGTH = /(^|[^\w.-])-?(?!0*\.?0+(?:px|rem|em|%|ch|vw|vh|pt)?(?![\w.%]))\d*\.?\d+(px|rem|em|%|ch|vw|vh|pt)(?![\w])/

/** The spacing declarations in a rule body that hold a length of their own. */
function rawSpacing(body: string): string[] {
  return [...body.matchAll(/(?:^|[;\s{])((?:grid-)?(?:row-|column-)?gap|padding[a-z-]*|margin[a-z-]*)\s*:\s*([^;}]+)/g)]
    .filter((match) => RAW_LENGTH.test((match[2] ?? '').replace(/var\([^)]*\)/g, '')))
    .map((match) => `${match[1] ?? ''}: ${(match[2] ?? '').trim()}`)
}

const ALIASES = /var\(--(muted|hair|rail|rule|(?:green|red|amber|accent)(?:-[a-z]+)?)\s*[,)]/g

describe('the answer and set-up cards (ADR 0052)', () => {
  it('space only with the spacing tokens, never a length of their own in any unit', () => {
    const found = sheets.flatMap(({ file, css }) => rules(css).flatMap((rule) => rawSpacing(rule.body).map((raw) => `${raw} in ${file} (${rule.selector})`)))
    expect(found).toEqual([])
  })

  it('catches a raw length in any unit, and lets 0 and tokens through', () => {
    for (const bad of ['gap: 0.25rem;', 'gap: 0.5rem;', 'padding: 50%;', 'grid-gap: 8px;', 'row-gap: 1em 2px;', 'padding-inline-start: 10px;', 'margin: 0 auto 4px;']) expect(rawSpacing(bad), bad).not.toEqual([])
    for (const ok of ['gap: 0;', 'gap: 0px;', 'margin: 0 auto;', 'padding: var(--space-2) var(--space-4);', 'margin-block: calc(var(--space-1) * -1);', 'gap: 0 var(--space-3);']) expect(rawSpacing(ok), ok).toEqual([])
  })

  it('use the sketch’s colour names, with no older alias and no raw fallback colour', () => {
    const found = sheets.flatMap(({ file, css }) => [...css.matchAll(ALIASES), ...css.matchAll(/var\(--[a-z0-9-]+\s*,\s*(?:#|rgb|hsl)[^)]*\)/g)].map((match) => `${match[0]} in ${file}`))
    expect(found).toEqual([])
  })

  it('draw one surface: the sketch’s radius and soft shadow, with no border', () => {
    const card = rules(sheets[0]?.css ?? '').find((rule) => rule.selector === '.card')?.body ?? ''
    expect(card).toContain('border-radius: var(--r-lg)')
    expect(card).toContain('box-shadow: var(--shadow-2)')
    expect(card).not.toMatch(/\bborder\s*:/)
    expect(card).toContain('outline: 1px solid transparent')
  })

  it('put no box inside a card: no border, ring, outline or shadow except on a surface, an exact control or a hairline', () => {
    const found = sheets.flatMap(({ file, css }) =>
      rules(css)
        .filter((rule) => /(^|[;\s])(border(-left|-right|-bottom|-inline[a-z-]*)?|outline|box-shadow)\s*:[ \t]*(?![ \t])(?!none|0\s*;|transparent)/.test(rule.body))
        .filter((rule) => rule.selector.split(',').some((selector) => !SURFACES.includes(selector.trim()) && !EDGED.has(selector.trim()) && !/:focus|:hover/.test(selector)))
        .map((rule) => `${rule.selector} in ${file}`),
    )
    expect(found).toEqual([])
  })
})
