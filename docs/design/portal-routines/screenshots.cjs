/* Shoots every screenshot the design notes embed from docs/design/portal-routines/, by driving the prototype.
   Run from the repository root: node docs/design/portal-routines/screenshots.cjs
   It uses the Playwright that the Portal installs (portal/node_modules). */
const path = require('path');
const fs = require('fs');

const root = path.resolve(__dirname, '..', '..', '..');
const { chromium } = require(require.resolve('playwright', { paths: [path.join(root, 'portal')] }));
const url = `file://${path.join(__dirname, 'prototype.html')}`;

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 1000 }, colorScheme: 'light', reducedMotion: 'no-preference' });
  const errors = [];
  page.on('pageerror', (e) => errors.push(`pageerror ${e.message}`));
  page.on('console', (m) => { if (m.type() === 'error') errors.push(`console ${m.text()}`); });
  const hideControls = () => page.addStyleTag({ content: '.testctl, .toast { display: none !important; }' });

  const log = (s) => console.log(s);
  const settle = () => page.waitForTimeout(700);
  const shot = async (name, o = {}) => {
    await page.evaluate(() => { if (document.activeElement) document.activeElement.blur(); });
    if (o.el) await page.locator(o.el).first().screenshot({ path: path.join(__dirname, `${name}.png`) });
    else {
      if (!o.keepScroll) await page.evaluate(() => window.scrollTo(0, 0));
      await page.screenshot({ path: path.join(__dirname, `${name}.png`), fullPage: !o.viewport });
    }
    log(`  wrote ${name}.png`);
  };
  const go = async (tab) => { await page.click(`.nav-a[data-arg="${tab}"]`); await settle(); };
  const sim = async (label) => {
    if (!(await page.$('.testctl-panel'))) await page.$eval('.testctl-toggle', (b) => b.click());
    await page.$eval(`.testctl button:has-text("${label}")`, (b) => b.click());
    await settle();
  };
  const replied = () => page.waitForFunction(() => !document.querySelector('main .dots') && !document.querySelector('main .face.fs-speaking') && !document.querySelector('main .face.fs-thinking'), null, { timeout: 15000 });
  const ask = async (text) => { await page.fill('[data-ask]', text); await page.keyboard.press('Enter'); await replied(); await settle(); };
  const newChat = async () => { await page.click('[data-act="newChat"]'); await settle(); };
  const instant = async () => { await page.click('[data-act="speed"][data-arg="instant"]'); await settle(); };
  const closeDialog = async () => { await page.keyboard.press('Escape'); await settle(); };

  log('The agents’ faces, from the hidden #faces page');
  await page.goto(`${url}#faces`);
  await hideControls();
  await settle();
  await shot('faces', { el: '.facesfig' });

  log('A normal week, as Alice');
  await page.goto(url);
  await hideControls();
  await settle();

  await go('workflows');
  await shot('routines');
  await page.click('#needs-h ~ .task [data-act="run"][data-arg="sw"]');
  await settle();
  await shot('run-approval');

  await go('workflows');
  await page.click('[data-act="workflow"][data-arg="nudge"]');
  await settle();
  await page.click('[data-act="watch"][data-arg="nudge"]');
  await settle();
  await instant();
  await shot('report-to-support');
  await page.click('[data-act="report"]');
  await settle();
  await page.click('[data-act="sendReport"]');
  await page.waitForTimeout(900);
  await shot('report-sent', { viewport: true });
  await closeDialog();

  await go('software');
  await page.click('[data-act="swHist"][data-arg="lg"]');
  await settle();
  await shot('software');
  await shot('security-risk', { el: '#risk-lj' });

  await go('workflows');
  await page.click('[data-act="workflow"][data-arg="nudge"]');
  await settle();
  await page.click('[data-act="editSched"][data-arg="nudge"]');
  await settle();
  await shot('routine-manage');

  await go('workflows');
  await page.click('[data-act="workflow"][data-arg="issues"]');
  await settle();
  await page.click('[data-act="editAppr"][data-arg="issues"]');
  await settle();
  await shot('routine-approvers');
  await page.click('[data-act="cancelAppr"]');
  await settle();
  await page.click('[data-act="n8nAsk"][data-arg="issues"]');
  await settle();
  await shot('open-in-n8n', { viewport: true });
  await page.click('[data-act="n8nOpen"]');
  await settle();
  await sim('Carol changes it in n8n');
  await shot('n8n-change-undo');
  await sim('The next run starts');
  await instant();
  await shot('n8n-run-stopped');

  await go('workflows');
  await page.click('[data-act="n8nNew"]');
  await settle();
  await shot('new-in-n8n', { viewport: true });
  await closeDialog();

  await go('agents');
  await shot('agent-library');
  await page.click('[data-act="agent"][data-arg="checker"]');
  await settle();
  await shot('agent-details', { viewport: true });
  await page.click('.dialog .chip:has-text("Only flag support")');
  await page.click('[data-act="agentSuggest"]');
  await settle();
  await shot('agent-change', { viewport: true });
  await closeDialog();
  await page.click('[data-act="agent"][data-arg="writer"]');
  await settle();
  await page.fill('#agent-text', 'Create the tickets without asking anyone');
  await page.click('[data-act="agentSuggest"]');
  await settle();
  await shot('agent-change-refused', { viewport: true });
  await closeDialog();

  await page.click('[data-act="libTab"][data-arg="tools"]');
  await settle();
  await shot('agent-library-tools');
  await page.click('.chip:has-text("Set a component")');
  await page.click('[data-act="toolAskGo"]');
  await settle();
  await page.locator('#tool-reply').scrollIntoViewIfNeeded();
  await page.evaluate(() => window.scrollBy(0, 120));
  await shot('tool-ask', { viewport: true, keepScroll: true });
  await page.click('[data-act="toolDraft"][data-arg="jiraComp"]');
  await settle();
  await shot('tool-draft', { viewport: true });
  await closeDialog();
  await page.$eval('[data-act="toolOpen"][data-arg="jiraCreate"]', (b) => b.click());
  await settle();
  await shot('tool-details', { viewport: true });
  await closeDialog();

  await page.click('[data-act="go"][data-arg="settings"]');
  await settle();
  await shot('settings');
  for (const tab of ['connections', 'people', 'usage']) {
    await page.click(`[data-act="setTab"][data-arg="${tab}"]`);
    await settle();
    await shot(`settings-${tab}`);
  }

  log('Home, and the Planner’s five answers');
  await sim('Start over');
  await go('home');
  await shot('home');
  await page.click('.chip[data-act="example"][data-arg="0"]');
  await replied();
  await page.fill('#sched-time', '09:00');
  await settle();
  await shot('planner-card');
  await newChat();
  await ask('Every Monday at 9am, sum up open tickets in GitLab');
  await shot('planner-flags');
  await newChat();
  await ask('Email me a list of open bugs every Monday');
  await shot('planner-cant');
  await newChat();
  await ask('A weekly summary of closed tickets in Confluence');
  await shot('planner-tool');
  await newChat();
  await ask('Keep track of Kubernetes releases');
  await shot('planner-watchlist');

  log('A test run that nobody answers');
  await newChat();
  await page.click('.chip[data-act="example"][data-arg="0"]');
  await replied();
  await page.fill('#sched-time', '09:00');
  await page.selectOption('select[data-fix="project"]', 'MOCK');
  await settle();
  await page.click('[data-act="turnOn"]');
  await settle();
  await page.click('[data-act="testRun"]');
  await page.waitForTimeout(500);
  await instant();
  await sim('4 working hours pass');
  await shot('run-escalated');
  await sim('Nobody answers');
  await go('workflows');
  await shot('workflows-no-answer');

  log('Day one, as Alice');
  await sim('Start over');
  await sim('Day one');
  await go('home');
  await shot('day-one');

  await browser.close();
  const stale = ['new-routine-understood', 'new-routine-flags', 'new-routine-plan', 'new-routine-schedule', 'new-routine-review', 'release-check-redirect', 'home-no-answer'];
  stale.forEach((n) => { const p = path.join(__dirname, `${n}.png`); if (fs.existsSync(p)) { fs.unlinkSync(p); log(`  removed ${n}.png, no note embeds it`); } });
  if (errors.length) { console.error(errors.join('\n')); process.exit(1); }
  log('done, no page errors');
})();
