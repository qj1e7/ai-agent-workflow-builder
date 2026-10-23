/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import indexHtml from '../../index.html?raw'
import { agentIdentity, KNOWN_AGENT_IDS } from './agents'
import { personTone } from './personTone'

// Vitest blanks a CSS import, even with ?raw.
const tokensCss = readFileSync(new URL('./tokens.css', import.meta.url), 'utf8')

type Tokens = ReadonlyMap<string, string>

function declarations(body: string): [string, string][] {
  return [...body.matchAll(/--([a-z0-9-]+)\s*:\s*([^;]+);/g)].map((match) => [match[1] ?? '', (match[2] ?? '').trim()])
}

function rulesAtTopLevel(css: string): { selector: string; body: string }[] {
  const rules: { selector: string; body: string }[] = []
  let depth = 0
  let selectorStart = 0
  let bodyStart = 0
  let selector = ''
  for (let index = 0; index < css.length; index += 1) {
    if (css[index] === '{') {
      if (depth === 0) {
        selector = css.slice(selectorStart, index).trim()
        bodyStart = index + 1
      }
      depth += 1
    } else if (css[index] === '}') {
      depth -= 1
      if (depth === 0) {
        rules.push({ selector, body: css.slice(bodyStart, index) })
        selectorStart = index + 1
      }
    }
  }
  return rules
}

const stripped = tokensCss.replace(/\/\*[\s\S]*?\*\//g, '')
const rules = rulesAtTopLevel(stripped)
const lightRules = rules.filter((rule) => rule.selector === ':root')
const darkRules = rules.filter((rule) => rule.selector === ":root[data-theme='dark']")
const light: Tokens = new Map(lightRules.flatMap((rule) => declarations(rule.body)))
const darkOverrides: Tokens = new Map(darkRules.flatMap((rule) => declarations(rule.body)))
const dark: Tokens = new Map([...light, ...darkOverrides])

function value(tokens: Tokens, name: string): string {
  const raw = tokens.get(name)
  if (raw === undefined) throw new Error(`--${name} is not declared in tokens.css`)
  return raw.replace(/var\(--([a-z0-9-]+)\)/g, (_match, inner: string) => value(tokens, inner))
}

function channels(tokens: Tokens, name: string): [number, number, number] {
  const hex = /^#([0-9a-f]{6})$/i.exec(value(tokens, name))?.[1]
  if (!hex) throw new Error(`--${name} is ${value(tokens, name)}, which is not a six-digit hex colour`)
  return [0, 2, 4].map((at) => parseInt(hex.slice(at, at + 2), 16)) as [number, number, number]
}

function luminance(rgb: readonly number[]): number {
  const [r = 0, g = 0, b = 0] = rgb.map((channel) => {
    const unit = channel / 255
    return unit <= 0.03928 ? unit / 12.92 : ((unit + 0.055) / 1.055) ** 2.4
  })
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

function contrast(tokens: Tokens, foreground: string, background: string): number {
  const [a, b] = [luminance(channels(tokens, foreground)), luminance(channels(tokens, background))]
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05)
}

const TEXT_ON: readonly (readonly [text: string, background: string])[] = [
  ['ink', 'bg'],
  ['ink', 'surface'],
  ['ink', 'hair'],
  ['muted', 'bg'],
  ['muted', 'surface'],
  ['muted', 'hair'],
  ['on-ink', 'ink'],
  ['on-ink', 'lead'],
  ['on-status', 'green'],
  ['on-status', 'red'],
  ['amber-ink', 'amber-soft'],
  ['amber-ink', 'surface'],
  ['amber-ink', 'bg'],
  ['red-ink', 'red-soft'],
  ['red-ink', 'surface'],
  ['red-ink', 'bg'],
  ['green-ink', 'green-soft'],
  ['green-ink', 'surface'],
  ['green-ink', 'bg'],
  ['lead', 'surface'],
  ['lead', 'bg'],
  ['checker', 'surface'],
  ['checker', 'bg'],
  ['trouble', 'surface'],
  ['trouble', 'bg'],
  ...[1, 2, 3, 4].flatMap((n) => [
    [`agent-${n}`, 'surface'],
    [`agent-${n}`, 'bg'],
    [`person-${n}-ink`, `person-${n}-bg`],
    ['face-ink', `agent-${n}-tint`],
  ] as const),
  ['face-ink', 'lead-tint'],
  ['face-ink', 'checker-tint'],
  ['face-ink', 'trouble-tint'],
  ['chip-ink', 'chip-bg'],
]

const TEXT_RATIO = 4.5
const RING_RATIO = 3

describe.each([
  ['light', light],
  ['dark', dark],
] as const)('the %s tokens', (_theme, tokens) => {
  it.each(TEXT_ON)('--%s on --%s is at least 4.5:1', (text, background) => {
    expect(contrast(tokens, text, background)).toBeGreaterThanOrEqual(TEXT_RATIO)
  })

  it.each([['bg'], ['surface']])('the focus ring is at least 3:1 against --%s', (background) => {
    expect(contrast(tokens, 'focus', background)).toBeGreaterThanOrEqual(RING_RATIO)
  })
})

describe('tokens.css', () => {
  it('has one light block and one dark block', () => {
    expect(lightRules.length).toBe(1)
    expect(darkRules.length).toBe(1)
  })

  it('overrides in the dark block only what the light block declares', () => {
    const orphans = [...darkOverrides.keys()].filter((name) => !light.has(name))
    expect(orphans).toEqual([])
  })

  it('keeps the status colours and the page colours different between the themes', () => {
    for (const name of ['bg', 'surface', 'ink', 'on-ink', 'amber', 'red', 'green', 'lead', 'focus']) {
      expect(value(dark, name), `--${name}`).not.toBe(value(light, name))
    }
  })

  it('matches the theme-color metas in index.html to the page background of each theme', () => {
    const meta = (scheme: string) =>
      new RegExp(`<meta name="theme-color" media="\\(prefers-color-scheme: ${scheme}\\)" content="(#[0-9a-fA-F]{6})"`).exec(indexHtml)?.[1]
    expect(meta('light')?.toLowerCase()).toBe(value(light, 'bg'))
    expect(meta('dark')?.toLowerCase()).toBe(value(dark, 'bg'))
  })

  it('declares every token the agent faces and the initials draw from', () => {
    const names = new Set<string>()
    const ids = [...KNOWN_AGENT_IDS, ...Array.from({ length: 200 }, (_, index) => `agent_${index}`)]
    for (const id of ids) {
      const { hue, tint } = agentIdentity(id)
      for (const colour of [hue, tint]) names.add(/^var\(--([a-z0-9-]+)\)$/.exec(colour)?.[1] ?? colour)
    }
    for (let index = 0; index < 200; index += 1) {
      const { bg, ink } = personTone(`person ${index}`)
      for (const colour of [bg, ink]) names.add(/^var\(--([a-z0-9-]+)\)$/.exec(colour)?.[1] ?? colour)
    }
    names.add('face-ink')
    names.add('face-lens')
    const missing = [...names].filter((name) => !light.has(name))
    expect(missing).toEqual([])
  })
})
