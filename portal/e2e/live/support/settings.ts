import { expect, request, type APIRequestContext, type Browser, type BrowserContext, type Locator, type Page } from '@playwright/test'

export const MOCK_MODEL_URL = process.env['MOCK_MODEL_URL'] ?? 'http://mock-model:8300'
export const MOCK_MODEL = 'mock-model'

type Json = Record<string, unknown>

export interface Person {
  id: string
  display: string
  email: string
  operator: boolean
  approver: boolean
  pending_approver: { confirmation_id: string; asked_by: string } | null
  signed_in: boolean
}

export interface Confirmation {
  confirmation_id: string
  kind: 'approver' | 'model_address'
  about: { id: string } | null
  digest: string
  you_can_decide: boolean
}

export interface ModelView {
  active: { base_url: string; model: string; key_hint: string } | null
  pending: { base_url: string; model: string; by: string; digest: string } | null
}

export interface HistoryLine {
  area: string
  by: string
  confirmed_by: string | null
  summary: string
}

export interface Answer<T> {
  status: number
  body: T
}

export class SettingsApi {
  private readonly http: APIRequestContext

  private constructor(http: APIRequestContext) {
    this.http = http
  }

  static async connect(baseURL: string): Promise<SettingsApi> {
    return new SettingsApi(await request.newContext({ baseURL }))
  }

  async dispose(): Promise<void> {
    await this.http.dispose()
  }

  async send<T = Json>(user: string, method: 'GET' | 'POST' | 'PUT' | 'DELETE', path: string, body?: unknown): Promise<Answer<T>> {
    const response = await this.http.fetch(path, { method, headers: { 'X-Dev-User': user }, ...(body === undefined ? {} : { data: body }) })
    const text = await response.text()
    return { status: response.status(), body: (text ? JSON.parse(text) : null) as T }
  }

  async get<T = Json>(user: string, path: string): Promise<T> {
    const answer = await this.send<T>(user, 'GET', path)
    expect(answer.status, `GET ${path} as ${user}`).toBe(200)
    return answer.body
  }

  async people(user = 'alice'): Promise<Person[]> {
    return (await this.get<{ people: Person[] }>(user, '/api/v1/people')).people
  }

  async person(email: string, user = 'alice'): Promise<Person | undefined> {
    return (await this.people(user)).find((p) => p.email.toLowerCase() === email.toLowerCase())
  }

  async confirmations(user: string): Promise<Confirmation[]> {
    return (await this.get<{ confirmations: Confirmation[] }>(user, '/api/v1/confirmations')).confirmations
  }

  async model(user = 'alice'): Promise<ModelView> {
    return this.get<ModelView>(user, '/api/v1/settings/model')
  }

  async history(user = 'alice'): Promise<HistoryLine[]> {
    return (await this.get<{ changes: HistoryLine[] }>(user, '/api/v1/settings/history')).changes
  }

  async ensurePerson(email: string, display: string, roles: { operator: boolean; approver: boolean }): Promise<Person> {
    const known = await this.person(email)
    if (known) return known
    const added = await this.send<Person>('alice', 'POST', '/api/v1/people', { email, display, ...roles })
    expect(added.status, `alice adds ${email}: ${JSON.stringify(added.body)}`).toBe(201)
    return added.body
  }

  async confirmApprover(personId: string, approver = 'bob'): Promise<void> {
    const open = (await this.confirmations(approver)).find((c) => c.kind === 'approver' && c.about?.id === personId)
    expect(open, `an Approver request about ${personId} is open`).toBeDefined()
    const decided = await this.send(approver, 'POST', `/api/v1/confirmations/${open?.confirmation_id ?? ''}/decisions`, { verdict: 'confirm', digest: open?.digest })
    expect(decided.status, `${approver} confirms: ${JSON.stringify(decided.body)}`).toBe(201)
  }

  async confirmAddress(approver = 'bob'): Promise<void> {
    const { pending } = await this.model(approver)
    if (!pending) return
    const decided = await this.send(approver, 'POST', '/api/v1/settings/model/address-decision', { verdict: 'confirm', digest: pending.digest })
    expect(decided.status, `${approver} confirms the address: ${JSON.stringify(decided.body)}`).toBe(200)
  }
}

const DESKTOP = { width: 1440, height: 900 }
const PHONE = { width: 390, height: 844 }

export interface ContextOptions {
  phone?: boolean
  video?: string
}

export async function signedInAs(browser: Browser, user: string, { phone = false, video }: ContextOptions = {}): Promise<BrowserContext> {
  const context = await browser.newContext({
    ...(phone ? { viewport: PHONE, isMobile: true, hasTouch: true } : { viewport: DESKTOP }),
    ...(video ? { recordVideo: { dir: video, size: DESKTOP } } : {}),
    locale: 'en-SG',
    timezoneId: 'Asia/Singapore',
  })
  await context.addInitScript((id) => window.localStorage.setItem('portal.dev-user', id), user)
  return context
}

export async function openSettings(page: Page, tab: 'model' | 'people' = 'model'): Promise<void> {
  await page.goto(tab === 'people' ? '/settings?tab=people' : '/settings')
  await expect(page.getByRole('heading', { level: 2, name: tab === 'people' ? 'People and roles' : 'AI model' })).toBeVisible()
}

export function settingsTab(page: Page, name: 'AI model' | 'People and roles'): Locator {
  return page.getByRole('group', { name: 'Settings sections' }).getByRole('button', { name: new RegExp(`^${name}`) })
}

export function personRow(page: Page, email: string): Locator {
  return page.getByRole('list', { name: 'People on the list' }).getByRole('listitem').filter({ hasText: email })
}

export const roleBox = (page: Page, role: 'Operator' | 'Approver', name: string): Locator => page.getByRole('checkbox', { name: `${role} for ${name}`, exact: true })

export async function connectAndSave(page: Page, { address = MOCK_MODEL_URL, key, model = MOCK_MODEL }: { address?: string; key: string; model?: string }): Promise<void> {
  await page.getByLabel('Provider').selectOption('other')
  await page.getByLabel('Address', { exact: true }).fill(address)
  await page.getByLabel('API key').fill(key)
  await page.getByRole('button', { name: 'Connect', exact: true }).click()
  const models = page.getByLabel('Model', { exact: true })
  await expect(models, 'the model list loads after Connect').toBeVisible({ timeout: 30_000 })
  await models.selectOption(model)
  await page.getByRole('button', { name: 'Test and save' }).click()
  await expect(page.getByRole('button', { name: 'Connect', exact: true }), 'the form is back at Connect once saved').toBeVisible({ timeout: 30_000 })
}

/** page.content() leaves out what is typed in fields, so their values are added. */
export async function everythingOnThePage(page: Page): Promise<string> {
  const fields = await page.locator('input, textarea, select').evaluateAll((els) => els.map((el) => (el as HTMLInputElement).value))
  return `${await page.content()}\n${fields.join('\n')}`
}
