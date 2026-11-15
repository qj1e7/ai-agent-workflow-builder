#!/usr/bin/env bash
# Runs the same Semgrep scan as the "SAST with Semgrep" step in .github/workflows/ci.yml, without Docker.
# It reads the Semgrep version and the rule packs from ci.yml, so the two cannot drift apart.
# Needs uv and network access to the Semgrep registry. Writes semgrep.json, semgrep.sarif and console.txt.
# Usage: scripts/semgrep-local.sh [out-dir]   (default docs/evidence/sast/<today>)
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

ci=".github/workflows/ci.yml"
version="$(sed -n 's/.*SEMGREP_IMAGE: semgrep\/semgrep:\([0-9.]*\)@.*/\1/p' "$ci")"
configs=()
while read -r pack; do configs+=(--config "$pack"); done < <(
  sed -n '/semgrep scan/,/sarif-output/p' "$ci" | grep -o -- '--config [^ ]*' | cut -d' ' -f2
)
if [ -z "$version" ] || [ "${#configs[@]}" -lt 2 ]; then
  echo "FAIL: could not read the Semgrep version or rule packs from $ci" >&2
  exit 1
fi

out="${1:-docs/evidence/sast/$(date +%Y-%m-%d)}"
mkdir -p "$out"

status=0
uv tool run --from "semgrep==$version" semgrep scan "${configs[@]}" \
  --metrics=off --error --exclude docs \
  --json-output="$out/semgrep.json" --sarif-output="$out/semgrep.sarif" . \
  >/dev/null 2>"$out/console.txt" || status=$?

python3 -I - "$out" "$version" "${configs[*]}" <<'PY'
import json, sys
data = json.load(open(f"{sys.argv[1]}/semgrep.json"))
# The JSON leaves out findings a nosemgrep comment suppresses. The SARIF keeps them, marked.
sarif = json.load(open(f"{sys.argv[1]}/semgrep.sarif"))["runs"][0]
suppressed = [r for r in sarif["results"] if r.get("suppressions")]
print(f"semgrep {data.get('version')} (ci.yml pins {sys.argv[2]})")
print(f"packs: {sys.argv[3].replace('--config ', '')}")
print(f"rules: {len(sarif['tool']['driver']['rules'])}")
print(f"files scanned: {len(data['paths']['scanned'])}")
print(f"findings: {len(data['results'])} open, {len(suppressed)} suppressed in the source")
for r in suppressed:
    where = r["locations"][0]["physicalLocation"]
    print(f"  suppressed: {r['ruleId']} at {where['artifactLocation']['uri']}:{where['region']['startLine']}")
parse = sorted({e.get('path') for e in data['errors'] if e.get('path')})
print(f"files Semgrep could not fully parse: {len(parse)}")
for path in parse:
    print(f"  {path}")
PY
echo "exit $status"
exit "$status"
