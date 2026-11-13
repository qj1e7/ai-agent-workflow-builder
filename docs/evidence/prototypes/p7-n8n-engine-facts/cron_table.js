// Runs inside the n8n container: node - < cron_table.js
// Uses n8n's own Schedule Trigger code and its cron library to list the next fire times of each rule.
const path = require('path');
const fs = require('fs');

const root = '/usr/local/lib/node_modules/n8n/node_modules/.pnpm';
const find = (prefix, rel) => path.join(root, fs.readdirSync(root).find((d) => d.startsWith(prefix)), rel);
const sched = require(find('n8n-nodes-base@file', 'node_modules/n8n-nodes-base/dist/nodes/Schedule/GenericFunctions.js'));
const coreDir = find('n8n-core@file', 'node_modules/n8n-core');
const { CronTime } = require(require.resolve('cron', { paths: [coreDir] }));
const cronVersion = require(require.resolve('cron/package.json', { paths: [coreDir] })).version;

const TZ = 'Asia/Singapore';
const FROM = new Date('2026-11-13T00:30:00Z');
const NODE_KEY = 'wfP7example:4f2b7f0e-0000-4000-8000-000000000001';

const cases = [
  ['daily 8:00', { field: 'days', triggerAtHour: 8, triggerAtMinute: 0 }],
  ['daily 9:00, minute left out', { field: 'days', triggerAtHour: 9 }],
  ['daily, hour and minute left out', { field: 'days' }],
  ['weekly Monday 9:00', { field: 'weeks', triggerAtDay: [1], triggerAtHour: 9, triggerAtMinute: 0 }],
  ['weekdays 7:30', { field: 'weeks', triggerAtDay: [1, 2, 3, 4, 5], triggerAtHour: 7, triggerAtMinute: 30 }],
  ['every hour at :15', { field: 'hours', hoursInterval: 1, triggerAtMinute: 15 }],
  ['every 5 hours at :00 (does not divide 24)', { field: 'hours', hoursInterval: 5, triggerAtMinute: 0 }],
  ['every 2 days at 8:00', { field: 'days', daysInterval: 2, triggerAtHour: 8, triggerAtMinute: 0 }],
  ['every 15 minutes', { field: 'minutes', minutesInterval: 15 }],
  ['monthly on the 1st at 9:00', { field: 'months', monthsInterval: 1, triggerAtDayOfMonth: 1, triggerAtHour: 9, triggerAtMinute: 0 }],
  ['cron 0 30 7 * * 1-5', { field: 'cronExpression', expression: '0 30 7 * * 1-5' }],
];

const rows = cases.map(([label, interval]) => {
  const full = sched.withIntervalDefaults(interval);
  const expression = sched.toCronExpression(full, NODE_KEY);
  const ct = new CronTime(expression, TZ);
  const next = [];
  let t = FROM;
  for (let i = 0; i < 3; i++) {
    const d = ct.getNextDateFrom(t, TZ);
    const js = d.toJSDate ? d.toJSDate() : new Date(d);
    next.push(js.toISOString());
    t = new Date(js.getTime() + 1000);
  }
  const filteredByRecurrence = sched.intervalToRecurrence(full, 0).activated;
  return { label, interval, expression, next_utc: next, recurrence_filter: filteredByRecurrence };
});

console.log(JSON.stringify({ cron: cronVersion, tz: TZ, from: FROM.toISOString(), node_key: NODE_KEY, rows }));
