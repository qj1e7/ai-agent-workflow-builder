/** A proposal's action line split at its first colon: "Create Jira ticket in MOCK: New releases" gives the action and the title. */
export function splitActionLine(line: string): { readonly action: string | null; readonly title: string } {
  const colon = line.indexOf(': ')
  if (colon < 1 || colon + 2 >= line.length) return { action: null, title: line }
  return { action: line.slice(0, colon), title: line.slice(colon + 2) }
}
