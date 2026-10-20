# Contributing

Read `AGENTS.md` first. It holds the team rules that you and your AI agent both follow.

## One-time setup

You need git, the GitHub CLI (log in with `gh auth login`), and Node.js 20 or later. pstack's scripts run on Node.

```sh
gh repo clone qj1e7/ai-agent-workflow-builder
cd ai-agent-workflow-builder
```

The team's pstack version is locked in `.claude/settings.json`. To print it:

```sh
node -p "require('./.claude/settings.json').extraKnownMarketplaces['pstack-claude'].source.ref"
```

Set up the tool you use. Claude Code gets the closest match to the team setup.

### Claude Code

1. Start Claude Code in the repo root and accept the prompt to trust the folder. pstack downloads and turns on by itself.
2. Install Matt Pocock's skills. You need to do this once per machine:

   ```sh
   claude plugin install mattpocock-skills@claude-plugins-official --scope project
   ```

3. Restart Claude Code, then run `/pstack:setup-pstack` to choose your models. See [Costs and plan limits](#costs-and-plan-limits).
4. To check, type `/pstack:` in Claude Code. pstack's skills should appear.

### Codex

Use the locked version from the command above in place of `<version>`:

```sh
codex plugin marketplace add michael-denyer/pstack-claude --ref <version>
codex plugin add pstack@pstack-claude
```

Then trust the pstack hook through `/hooks`. Skills such as `arena`, `interrogate` and `architect` run agents in parallel. If subagents are off, add this to `~/.codex/config.toml`:

```toml
[features]
multi_agent = true
```

### GitHub Copilot CLI

```sh
copilot plugin marketplace add michael-denyer/pstack-claude
copilot plugin install pstack@pstack-claude
```

Copilot cannot lock a plugin to a version, so you get the newest pstack. It can be a few days ahead of the team. The first skill that needs a model runs `setup-pstack`.

### Cursor

Install pstack from Cursor's plugin marketplace ([source](https://github.com/cursor/plugins/tree/main/pstack)). This is Lauren Tan's original. Cursor sets its version, and it does not read `.agents/playbooks/`. Cursor reads `AGENTS.md`, so the team rules still apply. When you open a PR, follow the steps in `.agents/playbooks/` yourself.

## Daily workflow

1. Pick or create a GitHub issue.
2. Create a branch from `main`.
3. Give your agent the task, for example: "Use poteto-mode to add the release check trigger. Issue #12."
4. pstack plans, builds, verifies, and opens a PR in our format.
5. Read the whole diff yourself. You own what you ship, not the agent.
6. A teammate reviews and approves. Then the PR is squash-merged into `main`.

## Upgrading pstack (once per sprint)

One person does this at the start of each sprint.

1. List recent releases:

   ```sh
   gh release list -R michael-denyer/pstack-claude -L 5
   ```

2. Read the release notes for changes to playbooks or skills that we use. Skim the diff of `plugins/pstack/hooks/` too, because hooks run code on every teammate's machine.
3. On a new branch, change `"ref"` in `.claude/settings.json` to the new tag.
4. Get the commit that the tag points at, and put it in `PSTACK_SHA` in `.github/workflows/pstack-playbooks.yml`:

   ```sh
   gh api repos/michael-denyer/pstack-claude/commits/<version> --jq .sha
   ```

5. Open a PR named `chore(ci): upgrade pstack to <version>`. CI checks that the tag points at that commit, and that our playbooks still match the new version.
6. If the playbook check fails, a step that our playbooks quote has changed. Update the quoted text in `.agents/playbooks/` in the same PR.
7. After the merge, everyone pulls `main` and restarts their tool. Codex users run `codex plugin marketplace remove pstack-claude`, then add it again with the new `--ref`.

## Run the checks locally

CI runs the same commands. You need [uv](https://docs.astral.sh/uv/) and Docker. Run the first block in each project folder, `platform-api` and `agent-runtime`.

```sh
cd platform-api
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run lint-imports   # platform-api only
uv run pytest
```

CI runs the tests inside the Docker image. To do the same, and to build the image that ships, run these from the repo root:

```sh
docker build --target test --tag platform-api:test platform-api
docker run --rm platform-api:test
docker build --target runtime --tag platform-api:runtime platform-api
```

Use `agent-runtime` in place of `platform-api` for the other project.

To fix formatting, run `uv run ruff format .`. After you change a dependency, run `uv lock` and commit the new `uv.lock`.

For the two scans, run them from the repo root. The image names and digests are in `.github/workflows/ci.yml`.

```sh
docker run --rm --volume "$PWD:/src" --workdir /src "$SEMGREP_IMAGE" \
  semgrep scan --config p/python --config p/dockerfile --config p/github-actions \
  --metrics=off --error --exclude docs .

docker run --rm --volume "$PWD:/repo" "$GITLEAKS_IMAGE" \
  detect --no-git --source /repo --redact --verbose
```

Set `SEMGREP_IMAGE` and `GITLEAKS_IMAGE` first. Copy their values from the `env` block of `ci.yml`.

## Costs and plan limits

pstack starts subagents. By default, `arena`, `architect` and `interrogate` run several models in parallel, so they can use up a Claude Pro plan quickly.

- Run `/pstack:setup-pstack` and choose only models that your plan includes.
- Keep `arena` and `interrogate` for contested designs and risky PRs.
