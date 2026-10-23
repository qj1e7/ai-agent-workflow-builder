import { test } from '@playwright/test'

export type Check = 'small-text' | 'tab-order'

interface Known {
  check: Check
  /** Matches `<project>/<state or walk name>`. */
  scope: RegExp
  /** Matches one violation, as the check words it. */
  found: RegExp
  why: string
}

// Findings the app still has. Each one is reported on every run and stops being excused when E2E_STRICT=1.
// Delete an entry when the app is fixed, so the guard goes back to failing on it.
const KNOWN: readonly Known[] = [
  {
    check: 'tab-order',
    scope: /^desktop\/overview$/,
    found: /^"Position in the run" .* then "Open the full run" /,
    why: 'On the wide overview Tab finishes the left column before the right rail, so it jumps back up the page to "Open the full run".',
  },
]

const strict = Boolean(process.env['E2E_STRICT'])

/** Returns the violations nobody knows about. Known ones are logged and attached to the test instead of failing it. */
export function withoutKnown(check: Check, scope: string, found: readonly string[]): string[] {
  const unexpected: string[] = []
  for (const violation of found) {
    const known = strict ? undefined : KNOWN.find((entry) => entry.check === check && entry.scope.test(scope) && entry.found.test(violation))
    if (!known) {
      unexpected.push(violation)
      continue
    }
    const note = `KNOWN FINDING ${check} in ${scope}: ${violation}. ${known.why}`
    test.info().annotations.push({ type: 'known finding', description: note })
    console.log(note)
  }
  return unexpected
}
