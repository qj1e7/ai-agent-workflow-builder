/// <reference types="node" />
import { readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { TEAMS_DOES_WORDS } from './settings/connections'

// The platform has no "post a message in Teams" ability: Teams carries approval requests only (inconsistency I1).
const PROMISE = /\b(post|posts|send|sends|sent|message|messages)\b[^.]{0,30}\bTeams\b/i
const SCREENS = ['agents', 'settings']

const sourcesOf = (folder: string) =>
  readdirSync(join(__dirname, folder))
    .filter((name) => /\.tsx?$/.test(name) && !/\.test\./.test(name))
    .map((name) => ({ name: `${folder}/${name}`, text: readFileSync(join(__dirname, folder, name), 'utf8') }))

describe('what a screen says about Teams', () => {
  it('says Teams sends approval requests to Approvers', () => {
    expect(TEAMS_DOES_WORDS).toBe('Sends approval requests to Approvers')
  })

  it('never promises a Teams message on How it works or Settings', () => {
    const promises = SCREENS.flatMap(sourcesOf).flatMap(({ name, text }) =>
      text.split('\n').filter((line) => PROMISE.test(line) && !/approval request/i.test(line)).map((line) => `${name}: ${line.trim()}`),
    )
    expect(promises).toEqual([])
  })
})
