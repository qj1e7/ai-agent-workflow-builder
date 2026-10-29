# Portal browser specs

The specs in `e2e/live/` run in a real browser against the whole stack, through the Portal's own address. Run them with `scripts/e2e.sh` from the repository root. See "The browser suite" in [../../e2e/README.md](../../e2e/README.md).

They run in a runner image (`e2e/Dockerfile.runner`) that holds the pinned Playwright and the dependencies from `package-lock.json`, so a `portal/node_modules` on your machine is never used. Docker is the only thing you need.

Screenshots land in `portal/e2e/out/live/shots`, which git ignores.
