declare const brand: unique symbol
type Brand<T, B extends string> = T & { readonly [brand]: B }

export type RunId = Brand<string, 'RunId'>
export type AgentId = Brand<string, 'AgentId'>
export type UserId = Brand<string, 'UserId'>
/** A door in the room wall: a connector key such as 'github' or 'jira'. */
export type DoorKey = Brand<string, 'DoorKey'>
/** 1-based, gapless per run. */
export type Seq = Brand<number, 'Seq'>
/** Epoch ms on the run's own timeline. Event ts, approval waits and every counter use this. */
export type RunTime = Brand<number, 'RunTime'>
/** Monotonic ms used only to pace beats. Never compared with RunTime: the brands stop that at compile time. */
export type WallTime = Brand<number, 'WallTime'>
/** A duration. Unbranded on purpose: durations mix freely. */
export type Ms = number

export const runId = (id: string): RunId => id as RunId
export const agentId = (id: string): AgentId => id as AgentId
export const userId = (id: string): UserId => id as UserId
export const doorKey = (key: string): DoorKey => key as DoorKey
export const seq = (n: number): Seq => n as Seq
export const runTime = (ms: number): RunTime => ms as RunTime
export const wallTime = (ms: number): WallTime => ms as WallTime
