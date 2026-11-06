/* How much an Operator sees on Home, in version 3 and version 4: words, visible controls and primary buttons, on a
   normal week and on day one, at 1280 wide. USER-JOURNEY-COMPARISON.md section 6 quotes it.
   Run from the repository root:
     node docs/design/ai-native-redesign/checks/home-weight.cjs
   Writes checks/results/home-weight.json. */
const path = require('path');
const fs = require('fs');
const { repo, chromium, openPage, makeKit } = require('./run.cjs');

const VERSIONS = [
  { version: 'v3', proto: path.join(repo, 'docs/design/portal-routines/prototype.html'), paths: require('./paths-v3.cjs') },
  { version: 'v4', proto: path.join(repo, 'docs/design/ai-native-redesign/prototype.html'), paths: require('./paths-v4.cjs') },
];
const STATES = [
  { state: 'normal week', prepare: async () => {} },
  { state: 'day one', prepare: (k) => k.setDay('one') },
];

const weigh = (page) => page.evaluate(() => {
  const m = document.querySelector('main');
  const shown = (sel) => [...m.querySelectorAll(sel)].filter((x) => x.getClientRects().length).length;
  return { words: m.innerText.split(/\s+/).filter(Boolean).length, controls: shown('button, a[href], input, textarea, select'), primary: shown('.btn.primary') };
});

(async () => {
  const browser = await chromium.launch();
  const rows = [];
  for (const v of VERSIONS) {
    for (const s of STATES) {
      const o = await openPage(browser, `file://${v.proto}`, { width: 1280, height: 1000, reduced: true, block: true });
      const k = makeKit(o.page, 1280, v.paths);
      await s.prepare(k);
      rows.push({ version: v.version, state: s.state, ...(await weigh(o.page)), errors: o.errors.length });
      await o.context.close();
    }
  }
  await browser.close();
  console.log('| Home | Words | Controls | Primary buttons |\n|---|---|---|---|');
  rows.forEach((r) => console.log(`| ${r.version}, ${r.state} | ${r.words} | ${r.controls} | ${r.primary} |`));
  if (rows.some((r) => r.errors)) { console.error('page errors while measuring'); process.exitCode = 1; }
  fs.writeFileSync(path.join(__dirname, 'results', 'home-weight.json'), `${JSON.stringify(rows, null, 2)}\n`);
})();
