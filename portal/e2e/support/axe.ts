import type { AxeResults } from 'axe-core'

/** The violations that fail a run: serious or critical, each with the nodes it names. Minor and moderate ones stay in the saved result. */
export function blockingViolations(axe: AxeResults): string[] {
  return axe.violations
    .filter((violation) => violation.impact === 'serious' || violation.impact === 'critical')
    .map((violation) => `${violation.id} (${violation.impact}): ${violation.nodes.map((node) => node.target.join(' ')).join(' | ')}`)
}
