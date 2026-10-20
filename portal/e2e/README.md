# Portal end-to-end evidence

One command builds the Portal image, serves it in demo mode and runs every spec in the pinned Playwright image:

```sh
cd portal
npm run e2e
```

Docker is the only thing you need. It takes about two minutes with a warm Docker cache (the image build is cached, the specs themselves take about 100 seconds).

Pass Playwright arguments to run less, for example `npm run e2e -- keyboard.spec.ts --project=phone`. A run with arguments keeps the evidence already in `e2e/out`. A run without arguments empties the evidence folders first, then checks at the end that every file exists.

## What comes out

Everything lands in `portal/e2e/out`, which git ignores.

| Path | What it holds |
|---|---|
| `shots/<project>/<state>.png` | One screenshot per state, for `desktop` (1440 by 900) and `phone` (390 by 844). The name is the full page. Where the page scrolls, `<state>.viewport.png` is the first screen. |
| `axe/<project>/<state>.json` | The full axe-core result for each state. |
| `video/overview-success.webm` | The overview in real time, from load through Bob approving to MOCK-142. |
| `results/` | Playwright's own scratch output. |

The state names are listed in `support/states.ts`. A TypeScript type ties each `record(...)` call to that list, and `inventory.spec.ts` fails the run if a screenshot or axe file is missing.

## Specs

| Spec | What it proves |
|---|---|
| `overview.spec.ts` | The overview at each stage of the live success run, plus the earlier runs list. |
| `run.spec.ts` | The run page for the success, failed and rejected runs, including scrub back, technical details and Retry run. |
| `builder.spec.ts` | The builder empty, planned and saved. |
| `approvals.spec.ts` | The approvals list, then the approval page as Alice, Carol and Bob, and after approving. |
| `inboxes.spec.ts` | The Teams inbox and the mock Jira after the live run finished. |
| `reduced-motion.spec.ts` | With reduced motion nothing that moves is running, and the approval pause reads fully. A control run without reduced motion proves the sampler can see movement. |
| `keyboard.spec.ts` | Tab order and focus rings on the overview and approval page. The user switcher, the transport and the approve button by keyboard alone. |
| `video.spec.ts` | Records the video. Desktop only. |
| `travel.spec.ts` | Samples at 10 Hz through the live run and fails when `[data-travel]`, `[data-ticket]` or `[data-speech]` overlaps a `[data-room-label]` by more than 1 px. It skips with a message when no `[data-room-label]` exists. |
| `guards.spec.ts` | Points each instrument at a page built to break its rule, so a pass means the check can fail. Desktop only. |
| `smoke.spec.ts` | Serving, security headers, font and demo mode. |
| `inventory.spec.ts` | Runs last and only when everything else passed. |

Every screenshot test also runs, on the state it just reached: axe (zero serious or critical violations), no sideways scroll, every button, link, input, select, summary and slider at least 44 by 44 px, and no visible text under 12px. Every test fails on a Content Security Policy violation or an uncaught page error.

## How states are reached

In demo mode every full page load restarts the in-memory mock, so the specs reach approval states by in-app navigation and the header's user switcher. The page clock is frozen after load (`support/clock.ts`) and moved with `page.clock.runFor`, so a state does not depend on how fast the machine is. CSS transitions run on the real clock, so each jump is followed by 1.2 seconds of real waiting before the shot. axe schedules work with `setTimeout`, so the clock is nudged by 1 ms while it runs.

The specs run inside the server's network namespace, so the page is at `http://localhost:8080`. That matters: `crypto.randomUUID`, which Run now uses, only exists in a secure context, and a plain `http://` host name is not one.

## Known findings

`support/known.ts` lists what the app still gets wrong. A listed finding is printed as `KNOWN FINDING ...` and does not fail the run. Run with `E2E_STRICT=1 npm run e2e` to make them fail. Delete an entry when the app is fixed.

## The live suite

`npm run e2e` runs against the demo mock. The specs in `e2e/live/` run against the real stack instead, so they are not part of `npm run e2e`. Run them with `scripts/e2e.sh` from the repository root. See "The browser suite" in [../../e2e/README.md](../../e2e/README.md).
