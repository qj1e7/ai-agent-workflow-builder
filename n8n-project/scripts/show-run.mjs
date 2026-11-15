// Show which nodes ran in the newest execution of a workflow, with item counts per output.
//   node C:\n8n\show-run.mjs <workflowId>
import fs from 'node:fs';

const id = process.argv[2];
const key = fs.readFileSync(`${process.env.USERPROFILE}\\.config\\opencode\\n8n-key`, 'utf8').trim();
const H = { headers: { 'X-N8N-API-KEY': key } };

const list = await (await fetch(`http://localhost:5678/api/v1/executions?limit=1&workflowId=${id}&includeData=true`, H)).json();
const ex = list.data?.[0];
if (!ex) {
  console.log('no executions for', id);
  process.exit(0);
}
console.log('execution', ex.id, ex.status);
const data = typeof ex.data === 'string' ? JSON.parse(ex.data) : ex.data;
const runData = data?.resultData?.runData || data?.resultData?.run_data || {};
for (const [name, runs] of Object.entries(runData)) {
  for (const run of runs) {
    const main = run.data?.main || [];
    const counts = main.map((g) => (g || []).length);
    console.log(`- ${name.padEnd(34)} started=${run.startedAt ? new Date(run.startedAt).toISOString().slice(11, 19) : '-'} outputs=[${counts.join(',')}]${run.error ? ` ERROR: ${run.error.message}` : ''}`);
  }
}
const ifRuns = runData['Anything to report?'] || [];
console.log('\nIF detail:', JSON.stringify(ifRuns.map((r) => ({ input: r.inputSource?.previousNodeOutput, out: (r.data?.main || []).map((g) => (g || []).map((i) => i.json?.hasAlerts ?? i.json)) })), null, 1).slice(0, 1200));
