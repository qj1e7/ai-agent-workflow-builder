/* Shoots every screen in the paths module at 1280x1000 and 390x844, light theme, full page, with the test controls and messages hidden.
   Run from the repository root:
     node docs/design/ai-native-redesign/checks/shots.cjs <prototype.html> <paths.cjs> <outdir> */
const path = require('path');
const fs = require('fs');
const { chromium, openPage, makeKit } = require('./run.cjs');

const SIZES = [
  { tag: 'desktop', width: 1280, height: 1000 },
  { tag: 'phone', width: 390, height: 844 },
];

async function main() {
  const [protoArg, pathsArg, outArg] = process.argv.slice(2).map((a) => path.resolve(a));
  if (!outArg) { console.error('Usage: node shots.cjs <prototype.html> <paths.cjs> <outdir>'); process.exit(2); }
  const paths = require(pathsArg);
  fs.mkdirSync(outArg, { recursive: true });
  const browser = await chromium.launch();
  let wrote = 0;
  for (const screen of paths.screens) {
    for (const size of SIZES) {
      const { context, page, errors } = await openPage(browser, `file://${protoArg}`, { width: size.width, height: size.height });
      const kit = makeKit(page, size.width, paths);
      await page.addStyleTag({ content: `${paths.hide || '.testctl, .toast'} { display: none !important; }` });
      await screen.prepare(kit);
      await kit.replied();
      await kit.settle(900);
      await page.evaluate(() => { if (document.activeElement) document.activeElement.blur(); window.scrollTo(0, 0); });
      const file = path.join(outArg, `${screen.name}-${size.tag}.png`);
      await page.screenshot({ path: file, fullPage: true });
      console.log(`wrote ${path.relative(process.cwd(), file)}${errors.length ? `  (page errors: ${errors.length})` : ''}`);
      wrote += 1;
      await context.close();
    }
  }
  await browser.close();
  console.log(`\n${wrote} screenshots in ${path.relative(process.cwd(), outArg)}`);
}
main().catch((e) => { console.error(e); process.exit(2); });
