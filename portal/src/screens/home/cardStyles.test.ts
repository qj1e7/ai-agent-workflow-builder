/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

// Vitest blanks a CSS import, even with ?raw, so the sheets are read as files.
const SHEETS = ['../../ui/Card.module.css', './AnswerCards.module.css', './SetupCard.module.css', './EditCard.module.css', './PartsList.module.css', '../drafted/Drafted.module.css']

/** The card bodies in Planner.module.css, which also holds the chat's own layout (another change owns that). */
const PLANNER_CARD = ['lines', 'caps', 'steps', 'moreChoices', 'note', 'buttons', 'ask', 'sent', 'starters', 'starter', 'more', 'lookedAt', 'actions', 'cardDone', 'cardOk', 'waiting']

const strip = (css: string) => css.replace(/\/\*[\s\S]*?\*\//g, '')

const planner = [...strip(readFileSync(new URL('./Planner.module.css', import.meta.url), 'utf8')).matchAll(/([^{}]+)\{([^{}]*)\}/g)]
  .filter((match) => (match[1] ?? '').split(',').every((selector) => PLANNER_CARD.includes(/^\s*\.([a-zA-Z]+)/.exec(selector)?.[1] ?? '')))
  .map((match) => `${match[1] ?? ''}{${match[2] ?? ''}}`)
  .join('\n')

const sheets = [...SHEETS.map((file) => ({ file, css: strip(readFileSync(new URL(file, import.meta.url), 'utf8')) })), { file: './Planner.module.css (card rules)', css: planner }]

function rules(css: string): { selector: string; body: string }[] {
  return [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map((match) => ({ selector: (match[1] ?? '').trim(), body: match[2] ?? '' }))
}

const CONTROL = /input|select|textarea|button|chip|choice|value|field|spin|input|summary|link/i

describe('the answer and set-up cards (ADR 0052)', () => {
  it('space only with the spacing tokens, never a pixel gap of their own', () => {
    const found = sheets.flatMap(({ file, css }) =>
      [...css.matchAll(/(?:^|[;{\s])((?:row-|column-)?gap|padding(?:-[a-z]+)?|margin(?:-[a-z]+)?)\s*:\s*([^;}]+)/g)]
        .filter((match) => /\d+px/.test(match[2] ?? ''))
        .map((match) => `${match[1] ?? ''}: ${(match[2] ?? '').trim()} in ${file}`),
    )
    expect(found).toEqual([])
  })

  it('use the sketch’s colour names, not the older aliases', () => {
    const found = sheets.flatMap(({ file, css }) => [...css.matchAll(/var\(--(muted|hair|rail|rule|green-[a-z]+|red-[a-z]+|amber(?:-[a-z]+)?|accent(?:-[a-z]+)?)\)/g)].map((match) => `--${match[1] ?? ''} in ${file}`))
    expect(found).toEqual([])
  })

  it('draw one surface: the sketch’s radius and soft shadow, with no border', () => {
    const card = rules(sheets[0]?.css ?? '').find((rule) => rule.selector === '.card')?.body ?? ''
    expect(card).toContain('border-radius: var(--r-lg)')
    expect(card).toContain('box-shadow: var(--shadow-2)')
    expect(card).not.toMatch(/\bborder\s*:/)
  })

  it('put no box inside the card: only a control, a chip or a hairline has an edge', () => {
    const found = sheets.flatMap(({ file, css }) =>
      rules(css)
        .filter((rule) => /(^|[;\s])border(-left|-right|-bottom)?\s*:\s*[^;]*\b(solid|dashed)/.test(rule.body) && !CONTROL.test(rule.selector))
        .map((rule) => `${rule.selector} in ${file}`),
    )
    expect(found).toEqual([])
  })
})
