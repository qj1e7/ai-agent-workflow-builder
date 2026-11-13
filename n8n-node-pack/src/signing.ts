import { createHmac, timingSafeEqual } from 'node:crypto';
import type { IWebhookFunctions, IWebhookResponseData } from 'n8n-workflow';

// The start and the wake are signed over named fields, one per line, so a signature can bind values
// the receiver knows itself, such as its own workflow id, and our API builds the same message.
export function sign(secret: string, fields: readonly (string | number)[]): string {
  return createHmac('sha256', secret).update(fields.join('\n')).digest('hex');
}

export function signedBy(secret: string, fields: readonly (string | number)[], signature: unknown): boolean {
  if (typeof signature !== 'string') return false;
  const expected = Buffer.from(sign(secret, fields), 'hex');
  const given = Buffer.from(signature, 'hex');
  return given.length === expected.length && timingSafeEqual(given, expected);
}

/** A field that goes into a signed message: no line breaks, so one message has one reading. */
export function isToken(value: unknown): value is string {
  return typeof value === 'string' && /^[A-Za-z0-9_.:-]{1,128}$/.test(value);
}

/** Answers the request itself, so n8n neither starts nor resumes anything. */
export function refuse(ctx: IWebhookFunctions, status: number, detail: string): IWebhookResponseData {
  const res = ctx.getResponseObject() as unknown as { status(code: number): { json(body: unknown): unknown } };
  res.status(status).json({ detail });
  return { noWebhookResponse: true };
}
