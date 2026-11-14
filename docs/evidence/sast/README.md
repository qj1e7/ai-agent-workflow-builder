# SAST evidence: Semgrep over the whole app

**Date.** 14 Nov 2026 (Singapore time).
**Code.** `main` at `a7ba7673`, after PR #263.
**Command.** `scripts/semgrep-local.sh docs/evidence/sast/2026-11-14`. It reads the Semgrep version and the rule packs from the "SAST with Semgrep" step in `.github/workflows/ci.yml`, so the local scan and the CI scan use the same rules. It runs Semgrep through `uv`, with no Docker.
**Result.** 0 open findings. 1 finding suppressed in the source, with its reason.

## What ran

| Item | Value |
|---|---|
| Tool | Semgrep 1.179.0, the version CI pins in `SEMGREP_IMAGE` |
| Rule packs | `p/python`, `p/dockerfile`, `p/github-actions`, `p/typescript`, `p/javascript`, `p/react`, `p/nginx`, `p/terraform` |
| Rules | 314 in the packs, 313 run |
| Files | 625 scanned. Semgrep scans the files git tracks. It skipped 1,074 under `docs/` (the same `--exclude docs` as CI) and 154 on its default ignore list, such as `tests/` folders |
| By folder | `portal` 325, `platform-api` 158, `infra` 43, `agent-runtime` 42, `n8n-node-pack` 14, `e2e` 10, `n8n-project` 8, `deploy` 7, `scripts` 6, `.github` 5, `contracts` 4, `dast` 2, `load` 1 |
| Open findings | 0 |
| Suppressed | 1. `keyvault-ensure-secret-expires` at `infra/modules/key_vault/main.tf:40` |

## The files

| File | What it holds |
|---|---|
| `2026-11-14/semgrep.json` | Semgrep's JSON report: results, parse errors and the list of scanned files |
| `2026-11-14/semgrep.sarif` | The SARIF report, the same format CI keeps. It also lists the suppressed finding, marked `inSource` |
| `2026-11-14/console.txt` | Semgrep's own summary, as printed |

## The one suppressed finding

The rule asks for an expiry date on every Key Vault secret. The secrets in `infra/modules/key_vault/main.tf` have none on purpose. The comment beside the resource says why. An expired secret would stop every Container App that reads it, and nothing rotates them yet. Checkov raises the same point as `CKV_AZURE_41`, and the same comment skips it. Rotating the secrets is open work.

## The same scan in CI

CI runs this scan on every pull request and every push to `main`. The run on the same commit, [CI run 43590669307](https://github.com/qj1e7/ai-agent-workflow-builder/actions/runs/43590669307), passed. Its `semgrep-report` artifact holds the same result: 314 rules, 0 open findings and the same suppressed one. GitHub deletes that artifact on 12 Feb 2027, so this folder keeps a copy in the repository.

## What this scan does not cover

- Semgrep could not parse a few lines in 12 files. It scanned the rest of each file. 8 Python files use syntax newer than Semgrep's parser: `type` aliases (Python 3.12) and `except A, B:` without brackets (Python 3.14). One TypeScript file uses a `never:` label, and `ci.yml` has `${{ }}` expressions inside shell snippets. The files are listed at the end of the script's output and in `semgrep.json` under `errors`. Semgrep's summary puts the parsed share at about 99.9% of lines.
- It is a pattern scan. It finds risky code shapes, not logic faults. The approval gate and the write gateway are proven by tests and reviews instead. See [the security page](../fyp/security.md).
- `docs/` is not scanned. It holds evidence and prototypes, not shipped code.
- Earlier scans of the Terraform code alone are in [`../iac/`](../iac/README.md).
