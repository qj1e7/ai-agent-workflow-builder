/* Drives a clickable prototype through named user scenarios, counts every interaction, checks the outcome.
   Run from the repository root:
     node docs/design/ai-native-redesign/checks/run.cjs <prototype.html> <paths.cjs> <out.json> [--only A,B@390]
   It also writes <out>.md, a table of every scenario. The other scripts in this folder reuse the helpers exported here. */
const path = require('path');
const fs = require('fs');

const repo = path.resolve(__dirname, '..', '..', '..', '..');
const { chromium } = require(require.resolve('playwright', { paths: [path.join(repo, 'portal')] }));

const STEP_TIMEOUT = 8000;

/* The default page identity is the first part of the address hash, such as "home" or "run". A paths module can replace it. */
const defaultScreenOf = (page) => page.evaluate(() => (location.hash.replace(/^#/, '').split('/')[0] || 'home'));

const trim = (v, n = 400) => {
  const s = typeof v === 'string' ? v : JSON.stringify(v);
  return s && s.length > n ? `${s.slice(0, n)}...` : s;
};

/* Opens a fresh page on the prototype. Pass block:true to stop the web font request, so a run never waits on the network. */
async function openPage(browser, url, { width = 1280, height = 1000, reduced = false, block = false } = {}) {
  const context = await browser.newContext({ viewport: { width, height }, reducedMotion: reduced ? 'reduce' : 'no-preference', colorScheme: 'light' });
  const page = await context.newPage();
  page.setDefaultTimeout(STEP_TIMEOUT);
  const errors = [];
  page.on('pageerror', (e) => errors.push(`pageerror ${e.message}`));
  page.on('console', (m) => { if (m.type() === 'error') errors.push(`console ${m.text()}`); });
  if (block) await page.route(/^https?:/, (route) => route.fulfill({ status: 200, contentType: 'text/css', body: '' }));
  await page.goto(url);
  await page.waitForTimeout(300);
  return { context, page, errors };
}

/* Steps that are not the user's: test controls, waiting, reading. Nothing here is counted. */
function makeKit(page, width, paths) {
  const menuSel = (name) => (paths.menu ? paths.menu(width, name) : `${width > 900 ? '.nav-a' : '.tab'}[data-arg="${name}"]`);
  const settle = (ms = 350) => page.waitForTimeout(ms);
  const replied = async () => {
    await page.waitForTimeout(150);
    await page.waitForFunction(() => !document.querySelector('main .dots') && !document.querySelector('main .face.fs-speaking') && !document.querySelector('main .face.fs-thinking'), null, { timeout: 20000 });
    await page.waitForTimeout(300);
  };
  const controls = async (fn) => {
    const wasOpen = !!(await page.$('.testctl-panel'));
    if (!wasOpen) await page.$eval('.testctl-toggle', (b) => b.click());
    await fn();
    if (await page.$('.testctl-panel')) await page.$eval('.testctl-toggle', (b) => b.click());
    await settle();
  };
  const press = (sel, label) => page.$eval(`.testctl ${sel}`, (b) => b.click()).catch((e) => { throw new Error(`test control not found: ${label}`); });
  return {
    page,
    width,
    settle,
    replied,
    wait: (ms) => page.waitForTimeout(ms),
    waitText: (re, timeout = 25000) => page.waitForFunction(([src, flags]) => new RegExp(src, flags).test(document.body.innerText), [re.source, re.flags], { timeout }),
    text: (sel = 'main') => page.innerText(sel),
    count: (sel) => page.locator(sel).count(),
    setUser: (u) => controls(() => press(`button[data-act="user"][data-arg="${u}"]`, `Act as ${u}`)),
    setDay: (d) => controls(() => press(`button[data-act="day"][data-arg="${d}"]`, `Show ${d}`)),
    sim: (label) => controls(() => page.$eval(`.testctl .testctl-sims button:has-text("${label}")`, (b) => b.click()).catch(() => { throw new Error(`test control not found: ${label}`); })),
    reset: () => controls(() => press('button[data-act="reset"]', 'Start over')),
    go: async (name) => { await page.click(menuSel(name)); await settle(); },
    ask: async (text) => { await page.fill('[data-ask]', text); await page.keyboard.press('Enter'); await replied(); },
    menuSel,
  };
}

/* The scenario's view of the page. Everything counted goes through click, press, field, select, ask or menu. */
function makeT(kit, paths, scenario) {
  const { page } = kit;
  const screenOf = paths.screenOf || defaultScreenOf;
  const c = { clicks: 0, fields: 0, selects: 0, navs: 0, decisions: 0 };
  const steps = [];
  const screens = [];
  const metrics = {};
  const failures = [];
  const seen = async () => { const s = await screenOf(page); if (!screens.includes(s)) screens.push(s); return s; };
  let started = false;
  const start = async () => { if (!started) { started = true; await seen(); } };

  /* Every counted step has the same shape: record where the user was, act, let the page settle, record where they are. */
  async function step(kind, label, opts, act) {
    await start();
    const before = await screenOf(page);
    await act();
    if (opts && opts.reply) await kit.replied();
    if (opts && opts.until) await kit.waitText(opts.until);
    await kit.settle();
    const after = await seen();
    const nav = kind !== 'field' && kind !== 'select' && after !== before;
    if (kind === 'click') c.clicks += 1;
    if (kind === 'field') c.fields += 1;
    if (kind === 'select') c.selects += 1;
    if (nav) c.navs += 1;
    if (opts && opts.decision) c.decisions += 1;
    steps.push({ n: steps.length + 1, kind, label, nav, decision: !!(opts && opts.decision), screen: after });
  }

  const t = {
    kit,
    page,
    click: (sel, label, opts) => step('click', label || sel, opts, () => page.locator(sel).first().click()),
    press: (key, label, opts) => step('click', label || `Press ${key}`, opts, () => page.keyboard.press(key)),
    field: (sel, value, label, opts) => step('field', label || sel, opts, () => page.locator(sel).first().fill(value)),
    select: (sel, value, label, opts) => step('select', label || sel, opts, () => page.locator(sel).first().selectOption(value)),
    /* Type a request and send it with Enter: one field and one click. Waits for the Planner's typed reply. */
    ask: async (text, label) => {
      await t.field('[data-ask]', text, `Type: ${label || text}`);
      await step('click', 'Press Enter to send', null, async () => { await page.keyboard.press('Enter'); await kit.replied(); });
    },
    menu: (name, label, opts) => step('click', label || `Menu: ${name}`, opts, () => page.locator(kit.menuSel(name)).first().click()),
    /* Test controls and anything else that is not the user. Never counted, never adds a screen. */
    setup: async (fn) => { await fn(kit); },
    metric: (name, value) => { metrics[name] = value; },
    expect: async (label, actual, check) => {
      const v = await actual;
      let ok;
      if (check === undefined) ok = !!v;
      else if (check instanceof RegExp) ok = check.test(String(v));
      else if (typeof check === 'function') ok = !!(await check(v));
      else if (typeof check === 'string') ok = String(v).includes(check);
      else ok = v === check;
      if (!ok) failures.push({ label, expected: check instanceof RegExp ? String(check) : typeof check === 'function' ? 'a condition' : check === undefined ? 'a truthy value' : String(check), actual: trim(v) });
      return ok;
    },
    expectText: async (label, re, sel = 'main') => t.expect(label, page.innerText(sel).catch(() => ''), re),
    expectCount: async (label, sel, n) => t.expect(label, page.locator(sel).count(), (v) => (typeof n === 'function' ? n(v) : v === n)),
  };
  return { t, c, steps, screens, metrics, failures, start };
}

async function runScenario(browser, url, paths, sc, { reduced = false } = {}) {
  const key = `${sc.id}@${sc.viewport}`;
  const base = { id: sc.id, key, title: sc.title, viewport: sc.viewport };
  if (sc.notPossible) {
    return { ...base, passed: false, notPossible: true, reason: sc.notPossible, failed: null, counts: null, steps: [], errors: [] };
  }
  const { context, page, errors } = await openPage(browser, url, { width: sc.viewport, reduced, block: true });
  const kit = makeKit(page, sc.viewport, paths);
  const run = makeT(kit, paths, sc);
  let stepError = null;
  try {
    await sc.run(run.t);
    await run.start();
  } catch (e) {
    stepError = e;
  }
  const failures = run.failures.slice();
  if (stepError) failures.push({ label: 'A step could not run', expected: 'the step to work', actual: trim(String(stepError.message).split('\n')[0]) });
  if (errors.length) failures.push({ label: 'No page or console errors', expected: 'none', actual: trim(errors) });
  const counts = { ...run.c, screens: run.screens.length, interactions: run.c.clicks + run.c.fields + run.c.selects, ...run.metrics };
  await context.close();
  return { ...base, passed: failures.length === 0, failed: failures[0] || null, failures, counts, screenList: run.screens, steps: run.steps, errors };
}

/* The control asserts text that is not on the page. If it ever passes, the checks cannot tell a pass from a fail. */
const CONTROL = {
  id: 'CONTROL-must-fail',
  title: 'Control: asserts text that does not exist, so it must fail',
  viewport: 1280,
  run: async (t) => { await t.expectText('The page says this impossible sentence', /Zebra pelican 4471 never appears/); },
};

function table(results, meta) {
  const real = results.filter((r) => !r.notPossible);
  const rows = results.map((r) => {
    const n = r.counts || {};
    const pass = r.notPossible ? 'not possible' : r.passed ? 'yes' : 'NO';
    const extra = r.counts ? Object.keys(n).filter((k) => !['clicks', 'fields', 'selects', 'navs', 'decisions', 'screens', 'interactions'].includes(k)).map((k) => `${k} ${n[k]}`).join(', ') : r.reason;
    return `| ${r.id} | ${r.viewport} | ${r.title} | ${pass} | ${n.clicks ?? '-'} | ${n.fields ?? '-'} | ${n.selects ?? '-'} | ${n.decisions ?? '-'} | ${n.screens ?? '-'} | ${extra || ''} |`;
  });
  return [
    `# Interaction counts, ${meta.version}`,
    '',
    `Prototype: \`${meta.prototype}\`. Paths: \`${meta.paths}\`.`,
    '',
    `Real scenarios: ${real.filter((r) => r.passed).length} passed, ${real.filter((r) => !r.passed).length} failed, ${results.filter((r) => r.notPossible).length} not possible. Control (must fail): ${meta.control.passed ? 'PASSED, which is wrong' : 'failed, as it should'}.`,
    '',
    '| Id | Width | Task | Passed | Clicks | Fields | Selects | Decisions | Screens | Notes |',
    '|---|---|---|---|---|---|---|---|---|---|',
    ...rows,
    '',
    'A click includes a key press on a button. Menu steps and page changes are included. A decision is also counted as a click, a select or a field. Test controls are never counted.',
    '',
  ].join('\n');
}

async function main() {
  const args = process.argv.slice(2).filter((a) => !a.startsWith('--'));
  const onlyArg = process.argv.find((a) => a.startsWith('--only='));
  const only = onlyArg ? onlyArg.slice(7).split(',') : null;
  if (args.length < 3) { console.error('Usage: node run.cjs <prototype.html> <paths.cjs> <out.json> [--only=A,B@390]'); process.exit(2); }
  const [protoArg, pathsArg, outArg] = args.map((a) => path.resolve(a));
  const paths = require(pathsArg);
  const url = `file://${protoArg}`;
  const browser = await chromium.launch();
  const results = [];
  for (const sc of paths.scenarios) {
    const key = `${sc.id}@${sc.viewport}`;
    if (only && !only.includes(sc.id) && !only.includes(key)) continue;
    const r = await runScenario(browser, url, paths, sc);
    results.push(r);
    const n = r.counts;
    console.log(r.notPossible ? `skip ${key}: not possible, ${r.reason}` : `${r.passed ? 'ok  ' : 'FAIL'} ${key}${n ? `  clicks ${n.clicks} fields ${n.fields} selects ${n.selects} decisions ${n.decisions} screens ${n.screens}` : ''}${r.passed ? '' : `  -> ${r.failed.label}: ${r.failed.actual}`}`);
  }
  const control = await runScenario(browser, url, paths, CONTROL);
  await browser.close();
  const real = results.filter((r) => !r.notPossible);
  const summary = { real: { total: real.length, passed: real.filter((r) => r.passed).length, failed: real.filter((r) => !r.passed).length, notPossible: results.filter((r) => r.notPossible).length }, control: { failed: !control.passed } };
  const meta = { prototype: path.relative(repo, protoArg), paths: path.relative(repo, pathsArg), version: paths.version || 'unnamed' };
  fs.mkdirSync(path.dirname(outArg), { recursive: true });
  fs.writeFileSync(outArg, `${JSON.stringify({ ...meta, summary, scenarios: results, control }, null, 2)}\n`);
  fs.writeFileSync(outArg.replace(/\.json$/, '.md'), table(results, { ...meta, control }));
  console.log(`\nReal scenarios: ${summary.real.passed} passed, ${summary.real.failed} failed, ${summary.real.notPossible} not possible (of ${results.length}).`);
  if (control.passed) console.log('WARNING: the control scenario CONTROL-must-fail PASSED. The checks cannot be trusted.');
  else console.log(`Control CONTROL-must-fail failed, as it should (${control.failed.label}).`);
  process.exit(summary.real.failed || control.passed ? 1 : 0);
}

module.exports = { repo, chromium, openPage, makeKit, defaultScreenOf };
if (require.main === module) main().catch((e) => { console.error(e); process.exit(2); });
