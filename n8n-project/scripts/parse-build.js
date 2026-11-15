// ── Edit these to fit your team's process ───────────────────────────────────
const PAGE_URL = 'https://YOUR-TENANT.atlassian.net/wiki/spaces/OMJ/pages/PAGE_ID/Cert+List';
const WARN_DAYS = 60;              // "needs action" window in days
const NEAR_DAYS = 30;              // second band on the card
const STALE_AFTER_DAYS = 365;      // expired longer than this = the page is stale, not a renewal task
const TIME_ZONE = 'Asia/Singapore';
const EMAIL_TO = 'qingtaoz@ncs.com.sg';
const MAX_LIST_PER_ENV = 10;       // rows per environment on the card
const MAX_ROWS_PER_SECTION = 20;   // rows per section in the email
const NO_ENV = '(no env)';

const ACTION_STEPS = [
  'Book the renewal / re-certification before the validity end date.',
  'Once renewed, update the VALIDITY END cell on the Cert List page (write the new date, not just "renewed").',
  'If you cannot renew in time, reply in the Teams thread with the reason and a committed target date.',
  'Fill in ENV and remove duplicate rows so the next run can post them as confirmed.',
];

// ── Confluence storage format → rows of plain text cells ────────────────────
function decodeEntities(s) {
  return s.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '\"')
    .replace(/&#39;/g, "'").replace(/&nbsp;/g, ' ').replace(/&amp;/g, '&');
}

function cellText(cellHtml) {
  const time = cellHtml.match(/<time[^>]*datetime=\"([^\"]+)\"/i);
  if (time) return time[1].trim();
  return decodeEntities(cellHtml.replace(/<br\s*\/?>/gi, ' ').replace(/<[^>]+>/g, ' '))
    .replace(/\s+/g, ' ').trim();
}

function extractTables(html) {
  const tables = [];
  for (const t of html.matchAll(/<table[^>]*>([\s\S]*?)<\/table>/gi)) {
    const rows = [];
    for (const r of t[1].matchAll(/<tr[^>]*>([\s\S]*?)<\/tr>/gi)) {
      const cells = [...r[1].matchAll(/<t[hd][^>]*>([\s\S]*?)<\/t[hd]>/gi)].map((c) => cellText(c[1]));
      if (cells.some((x) => x !== '')) rows.push(cells);
    }
    if (rows.length) tables.push(rows);
  }
  return tables;
}

// ── Dates ───────────────────────────────────────────────────────────────────
const MONTHS = {
  jan: 0, january: 0, feb: 1, february: 1, mar: 2, march: 2, apr: 3, april: 3, may: 4,
  jun: 5, june: 5, jul: 6, july: 6, aug: 7, august: 7, sep: 8, sept: 8, september: 8,
  oct: 9, october: 9, nov: 10, november: 10, dec: 11, december: 11,
};
const mo = (name) => MONTHS[name.toLowerCase()] ?? MONTHS[name.slice(0, 3).toLowerCase()];
const fy = (y) => (y < 100 ? 2000 + y : y);
const D = (y, m, d) => Date.UTC(y, m, d);

const DATE_ALT = [
  '\\d{4}-\\d{1,2}-\\d{1,2}',
  '\\d{1,2}\\s*[/.-]\\s*\\d{1,2}\\s*[/.-]\\s*\\d{2,4}',
  '\\d{1,2}\\s+[A-Za-z]{3,9}\\.?,?\\s+\\d{2,4}',
  '\\d{1,2}\\s*[/.-]\\s*[A-Za-z]{3,9}\\.?\\s*[/.-]?\\s*\\d{2,4}',
  '[A-Za-z]{3,9}\\.?\\s+\\d{1,2},?\\s+\\d{4}',
].join('|');
const DATE_RE = new RegExp(`(${DATE_ALT})`, 'gi');
const RENEWED_RE = new RegExp(`renew\\w*\\s*(?:on|:|-)?\\s*(?:on\\s*)?(${DATE_ALT})`, 'i');

function parseOne(raw) {
  const s = String(raw).replace(/\s+/g, ' ').trim();
  let m = s.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/);
  if (m) return D(+m[1], +m[2] - 1, +m[3]);
  m = s.match(/^(\d{1,2})\s*[/.-]\s*(\d{1,2})\s*[/.-]\s*(\d{2,4})$/);            // dd/mm/yyyy
  if (m) return D(fy(+m[3]), +m[2] - 1, +m[1]);
  m = s.match(/^(\d{1,2})\s*[/.-]?\s*([A-Za-z]{3,9})\.?\s*[/.-]?\s*(\d{2,4})$/);  // 31 Dec 2026
  if (m && mo(m[2]) !== undefined) return D(fy(+m[3]), mo(m[2]), +m[1]);
  m = s.match(/^([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s*(\d{4})$/);                     // Dec 31 2026
  if (m && mo(m[1]) !== undefined) return D(+m[3], mo(m[1]), +m[2]);
  return null;
}

// Reads the cell like a human: "renewed on X" wins, otherwise the last date written.
function readValidityEnd(cell) {
  const text = String(cell || '').trim();
  if (!text) return { kind: 'empty' };

  if (/never\s*expir|no\s*expir|not\s*using\s*cert|no\s*cert|n\/?a|not\s+applicable|permanent|static\s*key|public\s*key/i.test(text)) {
    return { kind: 'no-expiry' };
  }

  const dates = [...text.matchAll(DATE_RE)]
    .map((m) => ({ ms: parseOne(m[0].replace(/\s+/g, ' ')), raw: m[0].replace(/\s+/g, ' ').trim() }))
    .filter((d) => d.ms !== null);

  if (!dates.length) {
    if (/ssm\s*param|parameter\s*store|keycloak|imperva|acm|vault|portal|store|dosarrest|api\s*gateway/i.test(text)) {
      return { kind: 'stored-elsewhere' };
    }
    return { kind: 'unreadable' };
  }

  const renewed = text.match(RENEWED_RE);
  if (renewed && renewed[1]) {
    const ms = parseOne(renewed[1].replace(/\s+/g, ' '));
    if (ms !== null) return { kind: 'date', ms, basis: 'renewal date', used: renewed[1].replace(/\s+/g, ' ').trim(), dates };
  }

  const last = dates[dates.length - 1];
  return {
    kind: 'date',
    ms: last.ms,
    basis: dates.length > 1 ? 'last date in cell' : 'as written',
    used: last.raw,
    dates,
  };
}

function fmt(ms) {
  return new Intl.DateTimeFormat('en-GB', { timeZone: 'UTC', day: '2-digit', month: 'short', year: 'numeric' }).format(new Date(ms));
}

// ── Main ────────────────────────────────────────────────────────────────────
const body = $json?.body ?? $json;
const html = body?.storage?.value ?? body?.value ?? (typeof body === 'string' ? body : '');
if (!html) throw new Error('No page body in the Confluence response - check the credential and page id.');

const tables = extractTables(html);
if (!tables.length) throw new Error('No <table> found on the Cert List page.');

const END_RE = /validity\s*end|valid\s*end|expir/i;
const ENV_RE = /^env$|environment/i;
const NAME_RE = /\bname\b|holder|owner|system|service/i;

let headers = null;
let rows = [];
for (const table of tables) {
  const hi = table.findIndex((row) => row.some((c) => END_RE.test(c)));
  if (hi === -1) continue;
  headers = table[hi];
  rows = table.slice(hi + 1);
  break;
}
if (!headers) {
  throw new Error(`No column matching "VALIDITY END". Headers seen: ${tables.map((t) => t[0].join(' | ')).join(' // ').slice(0, 500)}`);
}

const idx = (re, fb) => { const i = headers.findIndex((x) => re.test(x)); return i === -1 ? fb : i; };
const envCol = idx(ENV_RE, -1);
const nameCol = idx(NAME_RE, 0);
const endCol = headers.findIndex((h) => END_RE.test(h));

const todayUtc = (() => {
  const p = new Intl.DateTimeFormat('en-CA', { timeZone: TIME_ZONE, year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date()).split('-');
  return Date.UTC(+p[0], +p[1] - 1, +p[2]);
})();

const actionable = [];
const stale = [];
const noExpiry = [];
const storedElsewhere = [];
const unreadable = [];

rows.forEach((row, n) => {
  const rawEnd = (row[endCol] ?? '').trim();
  const env = (envCol >= 0 ? (row[envCol] ?? '') : '').trim() || NO_ENV;
  const name = (row[nameCol] ?? '').trim() || `row ${n + 1}`;
  const v = readValidityEnd(rawEnd);

  if (v.kind === 'empty') return;
  if (v.kind === 'no-expiry') { noExpiry.push({ env, name, rawEnd }); return; }
  if (v.kind === 'stored-elsewhere') { storedElsewhere.push({ env, name, rawEnd }); return; }
  if (v.kind === 'unreadable') { unreadable.push({ env, name, rawEnd }); return; }

  const daysLeft = Math.round((v.ms - todayUtc) / 86400000);
  const item = {
    env, name, validityEnd: fmt(v.ms), daysLeft, basis: v.basis, rawEnd,
    marker: daysLeft < 0 ? '🔴' : daysLeft <= NEAR_DAYS ? '🟠' : '🟡',
  };
  if (daysLeft < -STALE_AFTER_DAYS) stale.push(item);
  else actionable.push(item);
});

// Merge identical rows; the removed ones become "needs confirming" evidence.
const duplicates = [];
const keepFirst = (list) => {
  const seen = new Set();
  for (let i = list.length - 1; i >= 0; i--) {
    const k = `${list[i].env}|${list[i].name}|${list[i].validityEnd}`;
    if (seen.has(k)) { duplicates.push({ ...list[i] }); list.splice(i, 1); } else { seen.add(k); }
  }
};
keepFirst(actionable);
keepFirst(stale);

actionable.sort((a, b) => a.daysLeft - b.daysLeft);
stale.sort((a, b) => a.daysLeft - b.daysLeft);

// ── Confirmed vs needs confirming ───────────────────────────────────────────
// Confirmed  = we know the date AND we know where it lives (ENV filled in).
// Everything else that is interesting goes to the email instead of the channel.
const attention = actionable.filter((i) => i.daysLeft <= WARN_DAYS);
const confirmed = attention.filter((i) => i.env !== NO_ENV);
const missingEnv = attention.filter((i) => i.env === NO_ENV);
const needsConfirmCount = missingEnv.length + unreadable.length + stale.length + duplicates.length;
const hasAlerts = confirmed.length > 0 || needsConfirmCount > 0;

const expiredCount = confirmed.filter((i) => i.daysLeft < 0).length;
const soonCount = confirmed.filter((i) => i.daysLeft >= 0 && i.daysLeft <= NEAR_DAYS).length;
const laterCount = confirmed.filter((i) => i.daysLeft > NEAR_DAYS).length;

const byEnv = new Map();
for (const item of confirmed) {
  if (!byEnv.has(item.env)) byEnv.set(item.env, []);
  byEnv.get(item.env).push(item);
}
const envOrder = [...byEnv.keys()].sort((a, b) => a.localeCompare(b));

const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const checkedAt = new Intl.DateTimeFormat('en-GB', { timeZone: TIME_ZONE, dateStyle: 'medium', timeStyle: 'short' }).format(new Date());
const notTrackedCount = noExpiry.length + storedElsewhere.length;

// Flat list for the optional AI interpretation step (one call, all rows).
const needsRows = [];
const pushNeed = (bucket, r) => needsRows.push({
  id: `n${needsRows.length + 1}`,
  bucket,
  env: r.env,
  name: r.name,
  cell: String(r.rawEnd || r.validityEnd || '').slice(0, 140),
});
missingEnv.forEach((r) => pushNeed('no-environment', r));
unreadable.forEach((r) => pushNeed('unreadable-date', r));
stale.forEach((r) => pushNeed('expired-long-ago', r));
duplicates.forEach((r) => pushNeed('duplicate-row', r));

const subject = confirmed.length
  ? `⚠️ ${confirmed.length} certificate${confirmed.length === 1 ? '' : 's'} need action`
  : '✅ Nothing confirmed due in this window';

// ── Teams card (confirmed rows only) ────────────────────────────────────────
const colorOf = (d) => (d < 0 ? 'Attention' : d <= NEAR_DAYS ? 'Warning' : 'Default');
const chipOf = (d) => (d < 0 ? `${Math.abs(d)}d overdue` : d === 0 ? 'today' : `in ${d}d`);

const statCol = (label, value, color) => ({
  type: 'Column', width: 1, horizontalAlignment: 'Center',
  items: [
    { type: 'TextBlock', text: String(value), size: 'Large', weight: 'Bolder', color, horizontalAlignment: 'Center' },
    { type: 'TextBlock', text: label, size: 'Micro', isSubtle: true, horizontalAlignment: 'Center', wrap: true },
  ],
});

const rowSet = (i) => ({
  type: 'ColumnSet', spacing: 'Small',
  columns: [
    { type: 'Column', width: 'stretch', items: [{ type: 'TextBlock', text: `${i.marker} ${i.name}`, wrap: true, size: 'Small' }] },
    { type: 'Column', width: 'auto', items: [{ type: 'TextBlock', text: i.validityEnd, size: 'Small', isSubtle: true, horizontalAlignment: 'Right' }] },
    { type: 'Column', width: 'auto', items: [{ type: 'TextBlock', text: chipOf(i.daysLeft), size: 'Small', weight: 'Bolder', color: colorOf(i.daysLeft), horizontalAlignment: 'Right' }] },
  ],
});

const envBlocks = [];
for (const env of envOrder) {
  const items = byEnv.get(env);
  envBlocks.push({ type: 'TextBlock', text: `${env} (${items.length})`, size: 'Small', weight: 'Bolder', separator: true });
  items.slice(0, MAX_LIST_PER_ENV).forEach((i) => envBlocks.push(rowSet(i)));
  if (items.length > MAX_LIST_PER_ENV) {
    envBlocks.push({ type: 'TextBlock', text: `… and ${items.length - MAX_LIST_PER_ENV} more in ${env}`, size: 'Small', isSubtle: true });
  }
}

const needsNote = needsConfirmCount
  ? `${needsConfirmCount} item(s) need a human look and were emailed to ${EMAIL_TO}: ${[
      missingEnv.length ? `${missingEnv.length} without ENV` : '',
      unreadable.length ? `${unreadable.length} unreadable date` : '',
      stale.length ? `${stale.length} stale row(s)` : '',
      duplicates.length ? `${duplicates.length} duplicate(s)` : '',
    ].filter(Boolean).join(', ')}.`
  : 'Everything on the page is confirmed and readable.';

const cardBody = [
  {
    type: 'Container', style: 'Attention', bleed: true,
    items: [
      { type: 'TextBlock', text: subject, size: 'Medium', weight: 'Bolder', wrap: true },
      { type: 'TextBlock', text: `Cert List · ${rows.length} rows read · checked ${checkedAt} (${TIME_ZONE})`, size: 'Small', isSubtle: true, wrap: true },
    ],
  },
  { type: 'ColumnSet', spacing: 'Small', separator: true, columns: [
    statCol('OVERDUE', expiredCount, 'Attention'),
    statCol(`DUE ≤ ${NEAR_DAYS}D`, soonCount, 'Warning'),
    statCol(`DUE ≤ ${WARN_DAYS}D`, laterCount, 'Default'),
  ] },
  ...(envBlocks.length ? envBlocks : [{ type: 'TextBlock', wrap: true, text: 'No certificate with a confirmed date and environment falls inside the reminder window.', isSubtle: true }]),
  { type: 'TextBlock', text: needsNote, size: 'Small', isSubtle: true, wrap: true, separator: true },
  { type: 'ActionSet', actions: [{ type: 'Action.OpenUrl', title: 'Open Cert List', url: PAGE_URL }] },
];

// ── Email (needs-confirming rows only) ──────────────────────────────────────
const emailSubject = needsConfirmCount
  ? `Cert List · ${needsConfirmCount} item(s) to confirm · ${confirmed.length} posted to Teams`
  : `Cert List · ${confirmed.length} expiring, nothing to confirm`;

const tableOf = (heads, list, cells) => {
  const th = heads.map((h) => `<th style="text-align:left;padding:6px 10px;border-bottom:2px solid #d2d0ce;background:#f3f2f1;font-size:12px">${h}</th>`).join('');
  const tr = list.map((r) => `<tr>${cells(r).map((c) => `<td style="padding:6px 10px;border-bottom:1px solid #edebe9;font-size:13px">${c}</td>`).join('')}</tr>`).join('');
  return `<table style="border-collapse:collapse;width:100%;margin-bottom:4px"><thead><tr>${th}</tr></thead><tbody>${tr}</tbody></table>`;
};

const block = (title, note, inner) => `<h3 style="margin:18px 0 4px;font-size:14px">${title}</h3>${note ? `<p style="margin:0 0 8px;color:#605e5c;font-size:13px">${note}</p>` : ''}${inner}`;
const cut = (s, n) => esc(String(s).slice(0, n));

const emailBlocks = [];
if (missingEnv.length) {
  emailBlocks.push(block(
    `No environment filled in (${missingEnv.length})`,
    'These look actionable but the page does not say where the certificate lives, so they are not posted to Teams.',
    tableOf(['Certificate', 'Validity end', 'Status'], missingEnv.slice(0, MAX_ROWS_PER_SECTION), (r) => [esc(r.name), r.validityEnd, r.daysLeft < 0 ? `overdue ${Math.abs(r.daysLeft)} days` : `in ${r.daysLeft} days`]),
  ));
}
if (unreadable.length) {
  emailBlocks.push(block(
    `Cannot read a date (${unreadable.length})`,
    'Write a real date in the VALIDITY END cell (e.g. 04 Dec 2026) - prose like "renewed yearly" is not parseable.',
    tableOf(['Environment', 'Certificate', 'Cell says'], unreadable.slice(0, MAX_ROWS_PER_SECTION), (r) => [esc(r.env), esc(r.name), `&quot;${cut(r.rawEnd, 90)}&quot;`]),
  ));
}
if (stale.length) {
  emailBlocks.push(block(
    `Expired more than ${Math.round(STALE_AFTER_DAYS / 30)} months ago (${stale.length})`,
    'Almost certainly stale rows rather than renewal tasks - update the date or mark the row retired.',
    tableOf(['Environment', 'Certificate', 'Validity end'], stale.slice(0, MAX_ROWS_PER_SECTION), (r) => [esc(r.env), esc(r.name), r.validityEnd]),
  ));
}
if (duplicates.length) {
  emailBlocks.push(block(
    `Duplicate rows on the page (${duplicates.length})`,
    'The same environment + certificate + date appears more than once; merged for this report.',
    tableOf(['Environment', 'Certificate', 'Validity end'], duplicates.slice(0, MAX_ROWS_PER_SECTION), (r) => [esc(r.env), esc(r.name), r.validityEnd]),
  ));
}

const emailHtml = [
  '<div style="font-family:\'Segoe UI\',Arial,sans-serif;color:#242424;max-width:820px">',
  `<h2 style="margin:0 0 2px;font-size:18px">${esc(emailSubject)}</h2>`,
  `<p style="margin:0 0 16px;color:#605e5c;font-size:13px">Teams channel <em>cert-expiry-reminder</em> gets only confirmed items (${confirmed.length}). The ${needsConfirmCount} below need a decision or a page fix before they can be posted.</p>`,
  '<!--AI-->',
  ...(emailBlocks.length ? emailBlocks : ['<p>Nothing needs confirming - every row has a readable date and an environment.</p>']),
  `<h3 style="margin:18px 0 4px;font-size:14px">What to do</h3><ol style="margin:0;padding-left:20px;font-size:13px">${ACTION_STEPS.map((s) => `<li style="margin-bottom:4px">${esc(s)}</li>`).join('')}</ol>`,
  ...(notTrackedCount ? [`<p style="margin-top:14px;color:#605e5c;font-size:12px">${notTrackedCount} row(s) keep the key elsewhere (SSM / Keycloak / Imperva / non-expiring keys) - no expiry tracked on this page.</p>`] : []),
  `<p style="margin-top:16px;font-size:12px"><a href="${PAGE_URL}">Open Cert List</a> · checked ${esc(checkedAt)} (${TIME_ZONE})</p>`,
  '</div>',
].join('');

// Plain-text mirror for the (disabled) SMTP node.
const teamsText = [
  subject,
  `Cert List · checked ${checkedAt} (${TIME_ZONE})`,
  '',
  ...envOrder.flatMap((env) => [`${env} (${byEnv.get(env).length}):`, ...byEnv.get(env).slice(0, MAX_LIST_PER_ENV).map((i) => `${i.marker} ${i.name} - ends ${i.validityEnd}, ${chipOf(i.daysLeft)}`), '']),
  needsNote,
  '',
  `Email copy: ${emailSubject}`,
  PAGE_URL,
].join('\n');

const teamsHtml = `<h3>${esc(subject)}</h3><p>Cert List · checked ${esc(checkedAt)} (${TIME_ZONE})</p>${envOrder.map((env) => `<p><strong>${esc(env)} (${byEnv.get(env).length})</strong></p><ul>${byEnv.get(env).slice(0, MAX_LIST_PER_ENV).map((i) => `<li>${i.marker} <strong>${esc(i.name)}</strong> - ends <strong>${i.validityEnd}</strong>, ${chipOf(i.daysLeft)}</li>`).join('')}</ul>`).join('')}<p>${esc(needsNote)}</p>`;

const teamsCard = {
  type: 'AdaptiveCard',
  version: '1.4',
  '$schema': 'http://adaptivecards.io/schemas/adaptive-card.json',
  msteams: { width: 'Full' },
  body: cardBody,
};

const teamsWebhookPayload = JSON.stringify({
  type: 'message',
  emailSubject,
  emailHtml,
  attachments: [{
    contentType: 'application/vnd.microsoft.card.adaptive',
    content: teamsCard,
  }],
});

return [{
  json: {
    hasAlerts,
    subject,
    emailSubject,
    checkedAt,
    pageUrl: PAGE_URL,
    emailTo: EMAIL_TO,
    rowsRead: rows.length,
    confirmedCount: confirmed.length,
    needsConfirmCount,
    expiredCount,
    soonCount,
    laterCount,
    missingEnvCount: missingEnv.length,
    unreadableCount: unreadable.length,
    staleCount: stale.length,
    duplicateCount: duplicates.length,
    notTrackedCount,
    byEnvCounts: envOrder.reduce((acc, e) => ({ ...acc, [e]: byEnv.get(e).length }), {}),
    confirmed,
    missingEnv,
    unreadable,
    stale: stale.slice(0, 20),
    duplicates,
    needsRows,
    teamsText,
    teamsHtml,
    teamsCard,
    emailHtml,
    teamsWebhookPayload,
  },
}];
