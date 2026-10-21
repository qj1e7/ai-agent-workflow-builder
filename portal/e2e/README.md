# Portal end-to-end evidence

One command builds the Portal image, serves it in demo mode and runs every spec in the pinned Playwright image:

```sh
cd portal
npm run e2e
```

Docker is the only thing you need. The specs run in a runner image (`e2e/Dockerfile.runner`) that holds the pinned Playwright and the dependencies from `package-lock.json`, so a `portal/node_modules` on your machine is never used. Docker reuses the install until the lockfile changes. A first run takes a few minutes while the images build. After that it takes about three minutes.

Pass Playwright arguments to run less, for example `npm run e2e -- keyboard.spec.ts --project=phone`. A run with arguments keeps the evidence already in `e2e/out`. A run without arguments empties the evidence folders first, then checks at the end that every file exists.

## What comes out

Everything lands in `portal/e2e/out`, which git ignores.

| Path | What it holds |
|---|---|
| `shots/<project>/<state>.png` | One screenshot per state, for `desktop` (1440 by 900) and `phone` (390 by 844) in the light theme, and `desktop-dark` and `phone-dark` in the dark theme. The name is the full page. Where the page scrolls, `<state>.viewport.png` is the first screen. |
| `axe/<project>/<state>.json` | The full axe-core result for each state. |
| `video/overview-success.webm` | The overview in real time, from load through Bob's recorded approval to MOCK-142. |
| `results/` | Playwright's own scratch output. |

The state names and the four projects are listed in `support/states.ts`. A TypeScript type ties each `record(...)` call to that list, and `inventory.spec.ts` fails the run if a screenshot or axe file is missing for any state in any project. The dark projects set the browser's colour scheme to dark, and the Portal follows it. They run only the specs that record states, so guards, keyboard, smoke and the video run in the light theme only.

## Specs

| Spec | What it proves |
|---|---|
| `overview.spec.ts` | The overview at each stage of the live success run as Alice, plus the earlier runs list. Then as Bob, who approves in place before the recorded approval, so the run writes MOCK-143. |
| `run.spec.ts` | The run page for the success, failed and rejected runs, including Instant, technical details and Retry run. Only an Operator is offered Retry run. |
| `builder.spec.ts` | The builder empty, planned and saved. |
| `approvals.spec.ts` | The approvals list, then the approval page as Alice, Carol and Bob, and after approving. Approve and Decline pressed in one tick send one decision. |
| `inboxes.spec.ts` | The Teams inbox and the mock Jira after the live run finished. |
| `reduced-motion.spec.ts` | With reduced motion nothing that moves is running, and the approval pause reads fully. A control run without reduced motion proves the sampler can see movement. |
| `keyboard.spec.ts` | Tab order and focus rings on the overview and approval page. The user switcher, the speed control and approving in place on the overview by keyboard alone. |
| `steady.spec.ts` | Runs last, in its own `steady-desktop` and `steady-phone` projects, so its real-time run neither slows the other specs nor is slowed by them. On the real clock, a full 1x run on the overview, then its replay. At 1440 the page shifts by 0.01 or less in all. At 390 the status block and the line's own rows shift by 0.01 or less over the replay with the inline panels held still, and the whole page by 0.11 or less over the live run. The rest is the panels opening under their stop, as the template does on the phone. Script forces at most 50 layouts over the replay, so the approval hold, which renders every 50 ms, does not measure the line each time. Each run prints its numbers as `STEADY {...}`: the layout shift, the frame times and the layouts that script forced. |
| `video.spec.ts` | Records the video. Desktop only. |
| `guards.spec.ts` | Points each instrument at a page built to break its rule, so a pass means the check can fail. Desktop only. |
| `smoke.spec.ts` | Serving, security headers, font and demo mode. |
| `inventory.spec.ts` | Runs last and only when everything else passed. |

Every screenshot test also runs, on the state it just reached: axe (zero serious or critical violations), no sideways scroll, every button, link, input, select, summary and slider at least 44 by 44 px, and no visible text under 12px. Every test fails on a Content Security Policy violation or an uncaught page error.

## How states are reached

In demo mode every full page load restarts the in-memory mock, so the specs reach approval states by in-app navigation and the header's user switcher. The page clock is frozen after load (`support/clock.ts`) and moved with `page.clock.runFor`, so a state does not depend on how fast the machine is. CSS transitions and the Tracker's Web Animations run on the real clock, so each jump is followed by 1.2 seconds of real waiting before the shot. axe schedules work with `setTimeout`, so the clock is nudged by 1 ms while it runs.

The seeded run reaches the approval about 18 seconds after load, and Bob's recorded approval lands at about 33 seconds and writes MOCK-142. A decision made in the demo before then replaces the recorded one, and the run writes MOCK-143. The specs find each state through the Tracker's own hooks: the status region's headline, `data-stop` and `data-state` on each stop, `data-gate` on the gate, and `data-at-head` and `data-speed` on the Tracker.

The specs run inside the server's network namespace, so the page is at `http://localhost:8080`, which browsers treat as a secure context. Run now works from a plain `http://` host name too. The live suite proves that in `04-plain-http-origin`.

## Known findings

`support/known.ts` lists what the app still gets wrong. A listed finding is printed as `KNOWN FINDING ...` and does not fail the run. Run with `E2E_STRICT=1 npm run e2e` to make them fail. Delete an entry when the app is fixed.

## The live suite

`npm run e2e` runs against the demo mock. The specs in `e2e/live/` run against the real stack instead, so they are not part of `npm run e2e`. Run them with `scripts/e2e.sh` from the repository root. See "The browser suite" in [../../e2e/README.md](../../e2e/README.md). It uses the same runner image, so it also needs only Docker.
