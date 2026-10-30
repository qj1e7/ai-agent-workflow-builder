import type { Me } from './types'

export const isOperator = (person: Me | null | undefined) => person?.roles.includes('operator') === true
