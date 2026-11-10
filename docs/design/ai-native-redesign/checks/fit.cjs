/* Fit check: every piece of text stays inside the card, box, button or pill that holds it, nothing is cut off,
   no two pieces of text sit on top of each other, buttons side by side line up, and the page never scrolls sideways.
   Run from the repository root:
     node docs/design/ai-native-redesign/checks/fit.cjs <prototype.html> <paths.cjs> <out.json> [--widths=1440,1280,1024,861,768,390] [--only=name,name]
   Prints one line per screen and width, and exits non-zero on any problem. A seeded control must be caught, to prove
   the check can fail. Text inside SVG (the n8n canvas) is not measured; look at the screenshots for it. */
const path = require('path');
const fs = require('fs');
const { repo, chromium, openPage, makeKit } = require('./run.cjs');

const WIDTHS = [1440, 1280, 1024, 861, 768, 390];

/* Runs in the page. Returns the problems found on what is drawn now. */
function measure() {
  const SKIP = '.testctl, script, style, noscript, template, option, svg, [data-fit-skip]';
  const px = (v) => parseFloat(v) || 0;
  const clear = (c) => !c || c === 'transparent' || /rgba\([^)]*,\s*0\)$/.test(c);
  const name = (el) => {
    if (!el || !el.tagName) return '?';
    const cls = typeof el.className === 'string' && el.className.trim() ? `.${el.className.trim().split(/\s+/).slice(0, 2).join('.')}` : '';
    return `${el.tagName.toLowerCase()}${el.id ? `#${el.id}` : ''}${cls}`;
  };
  const where = (el) => {
    const out = [];
    for (let e = el; e && e !== document.body && out.length < 4; e = e.parentElement) out.unshift(name(e));
    return out.join(' > ');
  };
  const hidden = (el) => {
    const shut = el.closest('details:not([open])');
    if (shut && !el.closest('summary')) return true;
    for (let e = el; e && e !== document.documentElement; e = e.parentElement) {
      const cs = getComputedStyle(e);
      if (cs.display === 'none' || cs.visibility === 'hidden' || cs.opacity === '0') return true;
      if ((cs.clip && cs.clip !== 'auto') || /inset\(50%/.test(cs.clipPath)) return true;
      const r = e.getBoundingClientRect();
      if (r.width <= 1 && r.height <= 1 && cs.overflow !== 'visible') return true;
    }
    return false;
  };
  const bgOf = (el) => {
    for (let e = el; e; e = e.parentElement) { const c = getComputedStyle(e).backgroundColor; if (!clear(c)) return c; }
    return 'rgb(255, 255, 255)';
  };
  const isBox = (el) => {
    if (/^(BUTTON|INPUT|SELECT|TEXTAREA|DIALOG)$/.test(el.tagName)) return true;
    const cs = getComputedStyle(el);
    if (cs.display === 'inline') return false;
    const sides = ['Top', 'Right', 'Bottom', 'Left'].filter((s) => px(cs[`border${s}Width`]) > 0 && cs[`border${s}Style`] !== 'none' && !clear(cs[`border${s}Color`])).length;
    if (sides >= 3) return true;
    return !clear(cs.backgroundColor) && el.parentElement && cs.backgroundColor !== bgOf(el.parentElement);
  };
  const scrolls = (cs) => /auto|scroll/.test(cs.overflowX) || /auto|scroll/.test(cs.overflowY);
  /* A scrolling area or a layer fixed to the screen holds its text the way a card does. */
  const boxOf = (el) => {
    for (let e = el; e && e !== document.body; e = e.parentElement) {
      const cs = getComputedStyle(e);
      if (isBox(e) || scrolls(cs) || cs.position === 'fixed') return e;
    }
    return null;
  };
  const layerOf = (el) => {
    for (let e = el; e && e !== document.body; e = e.parentElement) {
      const cs = getComputedStyle(e);
      if (cs.position === 'fixed' || cs.position === 'sticky') return e;
      if (cs.position === 'absolute' && cs.zIndex !== 'auto' && +cs.zIndex > 0) return e;
      if (e.tagName === 'DIALOG' || /^(dialog|menu|tooltip|alertdialog)$/.test(e.getAttribute('role') || '')) return e;
    }
    return document.body;
  };
  /* The part of a rect that shows through every clipping or scrolling ancestor. */
  const shown = (r, el) => {
    let { left, top, right, bottom } = r;
    for (let e = el.parentElement; e && e !== document.documentElement; e = e.parentElement) {
      const cs = getComputedStyle(e);
      if (cs.overflowX === 'visible' && cs.overflowY === 'visible') continue;
      const b = e.getBoundingClientRect();
      if (cs.overflowX !== 'visible') { left = Math.max(left, b.left); right = Math.min(right, b.right); }
      if (cs.overflowY !== 'visible') { top = Math.max(top, b.top); bottom = Math.min(bottom, b.bottom); }
    }
    return right - left > 1 && bottom - top > 1 ? { left, top, right, bottom } : null;
  };

  const problems = [];
  const lines = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const seenClip = new Set();
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const text = n.textContent.replace(/\s+/g, ' ').trim();
    const el = n.parentElement;
    if (!text || !el || el.closest(SKIP) || hidden(el)) continue;
    const range = document.createRange();
    range.selectNodeContents(n);
    const rects = [...range.getClientRects()].filter((r) => r.width > 0.5 && r.height > 0.5);
    if (!rects.length) continue;
    const snip = text.length > 48 ? `${text.slice(0, 45)}...` : text;

    /* Cut off: the text runs past an ancestor that hides overflow, or an ellipsis is showing. Text past a scrolling
       area is reached by scrolling, and nothing above a fixed layer clips it, so the walk stops at either. */
    for (let e = el; e && e !== document.body; e = e.parentElement) {
      const cs = getComputedStyle(e);
      if (scrolls(cs)) break;
      const hides = /hidden|clip/.test(cs.overflowX) || /hidden|clip/.test(cs.overflowY);
      if (hides) {
        const b = e.getBoundingClientRect();
        const out = rects.some((r) => r.left < b.left - 1 || r.right > b.right + 1 || (cs.overflowY !== 'visible' && r.bottom > b.bottom + 2) || (cs.overflowY !== 'visible' && r.top < b.top - 2));
        const ell = cs.textOverflow === 'ellipsis' && e.scrollWidth > e.clientWidth + 1;
        const clamp = cs.webkitLineClamp && cs.webkitLineClamp !== 'none' && e.scrollHeight > e.clientHeight + 2;
        if ((out || ell || clamp) && !seenClip.has(e)) {
          seenClip.add(e);
          problems.push({ kind: 'cut off', where: `${where(e)} (text in ${name(el)})`, text: snip });
        }
      }
      if (cs.position === 'fixed') break;
    }

    /* Spills: the text sticks out of the nearest card, box, button or pill. Sideways it must stay inside the padding's
       inner edge; up and down, inside the border (a line box can be taller than its line-height). */
    const box = boxOf(el);
    if (box) {
      const b = box.getBoundingClientRect();
      const cs = getComputedStyle(box);
      const inL = b.left + px(cs.borderLeftWidth) + px(cs.paddingLeft) - 1;
      const inR = b.right - px(cs.borderRightWidth) - px(cs.paddingRight) + 1;
      const inT = b.top + px(cs.borderTopWidth) - 2;
      const inB = b.bottom - px(cs.borderBottomWidth) + 2;
      const tall = scrolls(cs);
      const bad = rects.find((r) => r.left < inL || r.right > inR || (!tall && (r.top < inT || r.bottom > inB)));
      if (bad) {
        const by = Math.round(Math.max(inL - bad.left, bad.right - inR, inT - bad.top, bad.bottom - inB));
        problems.push({ kind: 'spills', where: `${where(el)} (box ${name(box)})`, text: `${snip} [${by}px]` });
      }
    }

    const layer = layerOf(el);
    rects.forEach((r) => { const s = shown(r, el); if (s) lines.push({ ...s, h: r.height, el, layer, snip }); });
  }

  /* Overlaps: two pieces of text in the same layer drawn on top of each other. */
  lines.sort((a, b) => a.top - b.top);
  const seenPair = new Set();
  for (let i = 0; i < lines.length; i += 1) {
    const a = lines[i];
    for (let j = i + 1; j < lines.length && lines[j].top < a.bottom; j += 1) {
      const b = lines[j];
      if (a.el === b.el || a.layer !== b.layer || a.el.contains(b.el) || b.el.contains(a.el)) continue;
      const w = Math.min(a.right, b.right) - Math.max(a.left, b.left);
      const h = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
      if (w > 2 && h > 0.5 * Math.min(a.h, b.h)) {
        const key = `${where(a.el)}|${where(b.el)}`;
        if (seenPair.has(key)) continue;
        seenPair.add(key);
        problems.push({ kind: 'overlaps', where: `${where(a.el)}  x  ${where(b.el)}`, text: `"${a.snip}" / "${b.snip}"` });
      }
    }
  }

  /* Uneven: buttons side by side in one row differ in height or sit off each other's centre. */
  const btnSel = 'button, a.btn, [role="button"], .btn';
  document.querySelectorAll('body *').forEach((parent) => {
    if (parent.closest(SKIP)) return;
    const d = getComputedStyle(parent).display;
    if (!/flex|grid/.test(d)) return;
    const kids = [...parent.children].filter((k) => k.matches(btnSel) && !hidden(k)).map((k) => ({ k, r: k.getBoundingClientRect() })).filter((x) => x.r.height > 0);
    for (let i = 0; i < kids.length; i += 1) {
      for (let j = i + 1; j < kids.length; j += 1) {
        const a = kids[i].r;
        const b = kids[j].r;
        const sameRow = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > 0.5 * Math.min(a.height, b.height);
        if (!sameRow) continue;
        /* A button drawn as a link has no box, so only its centre has to line up. */
        const boxed = (k) => { const cs = getComputedStyle(k); return !clear(cs.backgroundColor) || (px(cs.borderTopWidth) > 0 && cs.borderTopStyle !== 'none' && !clear(cs.borderTopColor)); };
        const dh = boxed(kids[i].k) && boxed(kids[j].k) ? Math.abs(a.height - b.height) : 0;
        const dc = Math.abs((a.top + a.bottom) / 2 - (b.top + b.bottom) / 2);
        if (dh > 2 || dc > 2) problems.push({ kind: 'uneven', where: `${where(kids[i].k)}  +  ${name(kids[j].k)}`, text: `heights ${Math.round(a.height)}/${Math.round(b.height)}, centres ${Math.round(dc)}px apart` });
      }
    }
  });

  const doc = document.documentElement;
  if (doc.scrollWidth > doc.clientWidth + 1) problems.push({ kind: 'sideways', where: 'page', text: `${doc.scrollWidth} > ${doc.clientWidth}` });
  return problems;
}

/* Proves the check can fail: a card with a word too long for it, a clipped label, and two labels drawn on top of each other. */
function seedControl() {
  const host = document.createElement('div');
  host.innerHTML = '<div style="width:120px;padding:8px;border:1px solid #888;margin:8px">Supercalifragilisticexpialidocious</div>'
    + '<div style="width:80px;overflow:hidden;white-space:nowrap;text-overflow:ellipsis">A label that is cut off</div>'
    + '<div style="position:relative;height:20px"><span style="position:absolute;left:0">First label</span><span style="position:absolute;left:4px">Second label</span></div>'
    + '<div style="display:flex;align-items:flex-start;gap:8px"><button style="height:40px">Tall</button><button style="height:28px">Short</button></div>';
  document.body.prepend(host);
}

async function main() {
  const args = process.argv.slice(2);
  const flag = (k) => { const a = args.find((x) => x.startsWith(`--${k}=`)); return a ? a.split('=')[1].split(',') : null; };
  const [protoArg, pathsArg, outArg] = args.filter((a) => !a.startsWith('--')).map((a) => path.resolve(a));
  if (!outArg) { console.error('Usage: node fit.cjs <prototype.html> <paths.cjs> <out.json> [--widths=...] [--only=...]'); process.exit(2); }
  const paths = require(pathsArg);
  const widths = (flag('widths') || WIDTHS).map(Number);
  const only = flag('only');
  const url = `file://${protoArg}`;
  const browser = await chromium.launch();

  const c = await openPage(browser, url, { width: 1280, height: 1000 });
  await c.page.evaluate(seedControl);
  const control = await c.page.evaluate(measure);
  await c.context.close();
  const kinds = new Set(control.map((p) => p.kind));
  const controlCaught = ['spills', 'cut off', 'overlaps', 'uneven'].every((k) => kinds.has(k));
  console.log(`control (must be caught): ${controlCaught ? 'caught' : `MISSED, found only ${[...kinds].join(', ') || 'nothing'}`}`);

  const rows = [];
  let total = 0;
  for (const screen of paths.screens.filter((s) => !only || only.includes(s.name))) {
    for (const width of widths) {
      const o = await openPage(browser, url, { width, height: width > 900 ? 1000 : 844, block: true });
      const kit = makeKit(o.page, width, paths);
      await o.page.addStyleTag({ content: '.testctl { display: none !important; }' });
      let problems;
      try {
        await screen.prepare(kit);
        await kit.replied();
        await kit.settle(900);
        problems = await o.page.evaluate(measure);
      } catch (e) {
        problems = [{ kind: 'could not open', where: screen.name, text: e.message.split('\n')[0] }];
      }
      problems.push(...o.errors.map((e) => ({ kind: 'error', where: 'console', text: e })));
      await o.context.close();
      total += problems.length;
      rows.push({ screen: screen.name, width, problems });
      console.log(`${screen.name.padEnd(28)} ${String(width).padStart(4)}  ${problems.length ? `${problems.length} problem${problems.length > 1 ? 's' : ''}` : 'ok'}`);
      problems.slice(0, 6).forEach((p) => console.log(`    ${p.kind}: ${p.where}  ${p.text}`));
    }
  }
  await browser.close();
  fs.mkdirSync(path.dirname(outArg), { recursive: true });
  fs.writeFileSync(outArg, `${JSON.stringify({ prototype: path.relative(repo, protoArg), paths: path.relative(repo, pathsArg), widths, controlCaught, total, rows }, null, 2)}\n`);
  console.log(`\n${total} problem${total === 1 ? '' : 's'}. wrote ${path.relative(process.cwd(), outArg)}`);
  process.exit(total || !controlCaught ? 1 : 0);
}
main().catch((e) => { console.error(e); process.exit(2); });
