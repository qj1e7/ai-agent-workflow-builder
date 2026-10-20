export type RunClock = (runId: string) => number

export const wallClock: RunClock = () => Date.now()
