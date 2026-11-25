/// <reference types="node" />
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import ts from 'typescript'
import { describe, expect, it } from 'vitest'

/**
 * The team lead's rule of 25 Nov: "yes" is never a noun in anything a person sees. A person
 * approves, and a run waits for approval. This reads every string and JSX text the Portal's
 * source holds, comments left out. The run page and its side panel have their own sweep.
 */
// Lower-case yes only: Yes is the name of a button and of Ask for approval's exit.
const YES_NOUN = /\b(?:[Aa]n?|[Yy]our|[Tt]he|[Tt]heir|[Nn]o|[Oo]ne|[Aa]ny|[Ss]econd) yes\b|['’]s yes\b|\byeses\b/
const LEFT_TO_THE_RUN_PAGE = ['screens/run']

function sources(folder: string): string[] {
  return readdirSync(folder).flatMap((name) => {
    const path = join(folder, name)
    if (statSync(path).isDirectory()) return LEFT_TO_THE_RUN_PAGE.includes(relative(__dirname, path)) ? [] : sources(path)
    return /\.tsx?$/.test(name) && !/\.(test|spec)\.|\.d\.ts$/.test(name) ? [path] : []
  })
}

function wordsIn(path: string): string[] {
  const file = ts.createSourceFile(path, readFileSync(path, 'utf8'), ts.ScriptTarget.Latest, true, path.endsWith('x') ? ts.ScriptKind.TSX : ts.ScriptKind.TS)
  const found: string[] = []
  const visit = (node: ts.Node) => {
    if (ts.isStringLiteralLike(node) || ts.isTemplateLiteralToken(node) || ts.isJsxText(node)) found.push(node.text)
    ts.forEachChild(node, visit)
  }
  visit(file)
  return found
}

describe('yes is never a noun in the Portal', () => {
  it('in any string or JSX text outside the run page', () => {
    const files = sources(__dirname)
    expect(files.length).toBeGreaterThan(100)
    const said = files.flatMap((path) => wordsIn(path).filter((words) => YES_NOUN.test(words)).map((words) => `${relative(__dirname, path)}: ${words.trim()}`))
    expect(said).toEqual([])
  })

  it('catches the shapes the rule names', () => {
    for (const words of ['Waits for a yes', 'Needs your yes', 'created after Bob’s yes', 'up to the yes.', "an Approver's yes"]) expect(words).toMatch(YES_NOUN)
    for (const words of ['Waits for approval', 'Bob approved.', 'Yes', 'Wire the Yes exit', 'Approvers say yes or no']) expect(words).not.toMatch(YES_NOUN)
  })
})
