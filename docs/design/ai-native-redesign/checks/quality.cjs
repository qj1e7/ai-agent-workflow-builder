/* Measures each screen: axe-core violations, sideways scroll at 390 px, running animations under reduced motion,
   console errors. Then a keyboard check from page load.
   Run from the repository root:
     node docs/design/ai-native-redesign/checks/quality.cjs <prototype.html> <paths.cjs> <out.json> */
const path = require('path');
const fs = require('fs');
const { repo, chromium, openPage, makeKit } = require('./run.cjs');

const AXE = path.join(repo, 'portal', 'node_modules', 'axe-core', 'axe.min.js');
const MAX_TABS = 80;

async function prepared(browser, url, paths, screen, width, reduced) {
  const o = await openPage(browser, url, { width, height: width > 900 ? 1000 : 844, reduced });
  const kit = makeKit(o.page, width, paths);
  await o.page.addStyleTag({ content: '.testctl { display: none !important; }' });
  await screen.prepare(kit);
  await kit.replied();
  await kit.settle(900);
  return { ...o, kit };
}

async function axeAt(page) {
  await page.addScriptTag({ path: AXE });
  const r = await page.evaluate(() => window.axe.run(document, { resultTypes: ['violations'] }));
  const byImpact = { critical: 0, serious: 0, moderate: 0, minor: 0 };
  r.violations.forEach((v) => { byImpact[v.impact] = (byImpact[v.impact] || 0) + 1; });
  return { byImpact, violations: r.violations.map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.length, help: v.help })) };
}

/* The page scrolls sideways when the document is wider than the window. The widest elements past the edge are the likely cause. */
function sideways(page) {
  return page.evaluate(() => {
    const doc = document.documentElement;
    const over = [...document.querySelectorAll('body *')]
      .map((el) => ({ el, r: el.getBoundingClientRect() }))
      .filter((x) => x.r.width > 0 && x.r.right > doc.clientWidth + 1)
      .sort((a, b) => b.r.right - a.r.right)
      .slice(0, 5)
      .map((x) => `${x.el.tagName.toLowerCase()}${x.el.id ? `#${x.el.id}` : ''}${x.el.className && typeof x.el.className === 'string' ? `.${x.el.className.trim().split(/\s+/).slice(0, 2).join('.')}` : ''} right=${Math.round(x.r.right)}`);
    return { scrolls: doc.scrollWidth > doc.clientWidth, scrollWidth: doc.scrollWidth, clientWidth: doc.clientWidth, widest: over };
  });
}

function animations(page) {
  return page.evaluate(() => {
    const running = document.getAnimations().filter((a) => a.playState === 'running');
    return { running: running.length, names: [...new Set(running.map((a) => a.animationName || (a.effect && a.effect.target && a.effect.target.className && String(a.effect.target.className.baseVal ?? a.effect.target.className)) || 'transition'))].slice(0, 6) };
  });
}

/* Press Tab from page load and count the presses to a target. Every stop on the way is checked for a visible focus style. */
async function keyboard(browser, url, paths, who) {
  const o = await openPage(browser, url, { width: 1280, height: 1000 });
  const kit = makeKit(o.page, 1280, paths);
  if (who === 'bob') {
    await kit.setUser('bob');
    await o.page.evaluate(() => {
      const probe = document.createElement('span');
      probe.tabIndex = -1;
      document.body.prepend(probe);
      probe.focus();
      probe.remove();
    });
  }
  const target = who === 'bob' ? paths.keyboard.approverTarget : paths.keyboard.operatorTarget;
  let presses = 0;
  let reached = false;
  const noRing = [];
  for (; presses < MAX_TABS && !reached;) {
    await o.page.keyboard.press('Tab');
    presses += 1;
    const info = await o.page.evaluate((sel) => {
      const el = document.activeElement;
      if (!el || el === document.body) return { name: '(body)', ring: false, hit: false };
      const cs = getComputedStyle(el);
      let ring = (cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0) || (cs.boxShadow && cs.boxShadow !== 'none');
      /* A field often shows its ring on a wrapper (focus-within). Compare the element and 3 parents with and without focus. */
      if (!ring) {
        const chain = [el];
        while (chain.length < 4 && chain[chain.length - 1].parentElement) chain.push(chain[chain.length - 1].parentElement);
        const sig = () => chain.map((n) => { const c = getComputedStyle(n); return `${c.outlineStyle}${c.outlineWidth}${c.boxShadow}${c.borderColor}`; }).join('|');
        const on = sig();
        el.blur();
        const off = sig();
        el.focus();
        ring = on !== off;
      }
      const label = `${el.tagName.toLowerCase()}${el.dataset && el.dataset.act ? `[${el.dataset.act}]` : ''} ${(el.getAttribute('aria-label') || el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 30)}`;
      return { name: label, ring: !!ring, hit: el.matches(sel) };
    }, target);
    if (!info.ring) noRing.push(`${presses}: ${info.name}`);
    reached = info.hit;
  }
  await o.context.close();
  return { target, who, presses: reached ? presses : null, reached, stopsWithoutVisibleFocus: noRing };
}

async function main() {
  const [protoArg, pathsArg, outArg] = process.argv.slice(2).map((a) => path.resolve(a));
  if (!outArg) { console.error('Usage: node quality.cjs <prototype.html> <paths.cjs> <out.json>'); process.exit(2); }
  const paths = require(pathsArg);
  const url = `file://${protoArg}`;
  const browser = await chromium.launch();
  const screens = [];
  for (const screen of paths.screens) {
    const row = { name: screen.name };
    for (const width of [1280, 390]) {
      const tag = width === 1280 ? 'desktop' : 'phone';
      const a = await prepared(browser, url, paths, screen, width, false);
      const ax = await axeAt(a.page);
      const sw = await sideways(a.page);
      row[tag] = { axe: ax.byImpact, axeViolations: ax.violations, sidewaysScroll: sw, consoleErrors: a.errors };
      await a.context.close();
      const r = await prepared(browser, url, paths, screen, width, true);
      row[tag].reducedMotion = await animations(r.page);
      await r.context.close();
    }
    screens.push(row);
    const d = row.desktop;
    const p = row.phone;
    console.log(`${screen.name.padEnd(26)} axe desktop ${JSON.stringify(d.axe)} phone ${JSON.stringify(p.axe)}  sideways@390 ${p.sidewaysScroll.scrolls ? `YES ${p.sidewaysScroll.scrollWidth}>${p.sidewaysScroll.clientWidth}` : 'no'}  animations(reduced) ${d.reducedMotion.running}/${p.reducedMotion.running}  errors ${d.consoleErrors.length + p.consoleErrors.length}`);
  }
  const keys = [await keyboard(browser, url, paths, 'operator'), await keyboard(browser, url, paths, 'bob')];
  keys.forEach((k) => console.log(`keyboard ${k.who}: ${k.reached ? `${k.presses} Tab presses to ${k.target}` : `did not reach ${k.target} in ${MAX_TABS}`}; stops without a visible focus style: ${k.stopsWithoutVisibleFocus.length}${k.stopsWithoutVisibleFocus.length ? ` (${k.stopsWithoutVisibleFocus.slice(0, 4).join('; ')})` : ''}`));
  await browser.close();
  fs.mkdirSync(path.dirname(outArg), { recursive: true });
  fs.writeFileSync(outArg, `${JSON.stringify({ prototype: path.relative(repo, protoArg), paths: path.relative(repo, pathsArg), screens, keyboard: keys }, null, 2)}\n`);
  console.log(`\nwrote ${path.relative(process.cwd(), outArg)}`);
}
main().catch((e) => { console.error(e); process.exit(2); });
