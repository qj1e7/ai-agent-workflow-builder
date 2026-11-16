// What n8n 2.42.6 runs for a Schedule Trigger rule that leaves parts out, as its editor saves one.
// n8n's own Workflow loader fills in each parameter's default before the trigger makes its cron.
// Run inside the pinned n8n image, printing q12b_schedule_defaults.txt:
//   docker run --rm --network none --entrypoint node \
//     -v "$PWD/q12b_schedule_defaults.js:/probe.js:ro" <the pinned n8n image> /probe.js
const path = require('path')
const find = (p) => require('child_process').execSync(`find / -path "${p}" 2>/dev/null | head -1`).toString().trim()
const { Workflow } = require(find('*n8n-workflow/dist/cjs/index.js'))
const nodePath = find('*nodes-base/dist/nodes/Schedule/ScheduleTrigger.node.js')
const { ScheduleTrigger } = require(nodePath)
const schedule = require(path.join(path.dirname(nodePath), 'GenericFunctions.js'))
const type = new ScheduleTrigger()
const nodeTypes = { getByNameAndVersion: () => type, getByName: () => type, getKnownTypes: () => ({}) }
const cases = {
  editor_3am_default_minute: { rule: { interval: [{ triggerAtHour: 3 }] } },
  editor_days_3_05: { rule: { interval: [{ triggerAtHour: 3, triggerAtMinute: 5 }] } },
  editor_untouched: {},
  editor_weeks_mon_9: { rule: { interval: [{ field: 'weeks', triggerAtDay: [1], triggerAtHour: 9 }] } },
  editor_hours: { rule: { interval: [{ field: 'hours' }] } },
  null_minute: { rule: { interval: [{ field: 'days', triggerAtHour: 3, triggerAtMinute: null }] } },
  rule_without_interval: { rule: {} },
  empty_interval_list: { rule: { interval: [] } },
  empty_item: { rule: { interval: [{}] } },
  months_default: { rule: { interval: [{ field: 'months' }] } },
  minutes_default: { rule: { interval: [{ field: 'minutes' }] } },
  cron_left_out: { rule: { interval: [{ field: 'cronExpression' }] } },
}
for (const [name, parameters] of Object.entries(cases)) {
  const node = { id: 'n1', name: 'Schedule Trigger', type: 'n8n-nodes-base.scheduleTrigger', typeVersion: 1.3, position: [0, 0], parameters }
  const workflow = new Workflow({ id: 'w1', nodes: [node], connections: {}, active: false, nodeTypes, settings: {} })
  const filled = workflow.getNode('Schedule Trigger').parameters
  const { interval = [{}] } = filled.rule || {}
  const crons = interval.map(schedule.withIntervalDefaults).map((rule) => schedule.toCronExpression(rule, 'w1:n1'))
  console.log(name, JSON.stringify(filled.rule), JSON.stringify(crons))
}
