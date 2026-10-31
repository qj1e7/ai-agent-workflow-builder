import type { Me } from './types'

export const isOperator = (person: Me | null | undefined) => person?.roles.includes('operator') === true

/** Signed in, but no Operator has put them on the People list, so the platform refuses them everything else. */
export const notOnTheList = (person: Me | null | undefined) => person?.on_list === false
