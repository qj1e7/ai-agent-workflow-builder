#!/usr/bin/env bash
# Renders every Mermaid block in docs/design/diagrams.md to a PNG in docs/evidence/diagrams/, which proves each one parses.
# Then checks the routes, event kinds and identifiers in the file against the contracts and the code,
# the ER diagrams' tables against the migrations, and the CI/CD diagram's jobs against .github/workflows/.
# Needs Docker and python3. Prints PASS or FAIL.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

# Mermaid CLI 11.17.1, published 24 Sep 2026, pinned by digest.
MERMAID_IMAGE="${MERMAID_IMAGE:-minlag/mermaid-cli:11.17.1@sha256:7b18341ab7398a0cfd290fdbf066243151c0adb4cbf5b81d8cf074f82019ec6f}"

doc="docs/design/diagrams.md"
out="docs/evidence/diagrams"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

mkdir -p "$out"
rm -f "$out"/*.png

# Each block is named after the "## " heading above it.
awk -v dir="$work" '
  /^## / { title = tolower(substr($0, 4)); gsub(/[^a-z0-9]+/, "-", title); gsub(/^-|-$/, "", title) }
  /^```mermaid$/ { n++; file = sprintf("%s/%02d-%s.mmd", dir, n, title); inside = 1; next }
  /^```$/ && inside { inside = 0; close(file); next }
  inside { print > file }
' "$doc"

# Class diagrams draw with the state diagram's settings in this Mermaid version, so both say useMaxWidth false.
cat > "$work/config.json" <<'JSON'
{"theme": "default", "flowchart": {"useMaxWidth": false}, "sequence": {"useMaxWidth": false}, "class": {"useMaxWidth": false}, "state": {"useMaxWidth": false}, "er": {"useMaxWidth": false}}
JSON

status=0
for source in "$work"/*.mmd; do
  name="$(basename "$source" .mmd)"
  # The browser profile lives in memory, so a nearly full Docker disk cannot stop the render.
  if docker run --rm --tmpfs /tmp:size=512m -u "$(id -u):$(id -g)" -v "$work:/data" "$MERMAID_IMAGE" \
    -i "/data/$name.mmd" -o "/data/$name.png" -c /data/config.json -b white -s 2 >"$work/$name.log" 2>&1; then
    cp "$work/$name.png" "$out/$name.png"
    echo "rendered $out/$name.png"
  else
    echo "FAIL: $name did not render" >&2
    cat "$work/$name.log" >&2
    status=1
  fi
done

python3 -I - "$doc" <<'PY' || status=1
import json, pathlib, re, sys

doc = pathlib.Path(sys.argv[1]).read_text()
problems = []

openapi = json.loads(pathlib.Path("contracts/openapi.json").read_text())
api_paths = list(openapi["paths"])


def path_pattern(path):
    parts = re.split(r"(\{[^}]+\}|\.\.\.)", path)
    return "^" + "".join("[^/ ]+" if p.startswith("{") else "[^ ]+" if p == "..." else re.escape(p) for p in parts) + "$"


for route in sorted(set(re.findall(r"(/(?:api|internal)/v1/[A-Za-z0-9_{}./-]*[A-Za-z0-9_}.])", doc))):
    if route.endswith(".") and not route.endswith("..."):
        route = route[:-1]
    pattern = path_pattern(route)
    if not any(re.match(pattern, p) or re.match(path_pattern(p), route) for p in api_paths):
        problems.append(f"route {route} is not in contracts/openapi.json")

agent_api = pathlib.Path("agent-runtime/src/agent_runtime/api.py").read_text()
for route in sorted(set(re.findall(r"(?<![a-z/])(/v1/[a-z]+(?:/[a-z]+)*)", doc))):
    if f'"{route}"' not in agent_api:
        problems.append(f"route {route} is not an Agent API route in agent_runtime/api.py")

webhooks = set()
for f in pathlib.Path("platform-api/src/platform_api/orchestration/workflows").glob("*.n8n.json"):
    for node in json.loads(f.read_text())["nodes"]:
        if node["type"].endswith(".webhook"):
            webhooks.add(node["parameters"]["path"])
for base, legs in re.findall(r"/webhook/([a-z-]+)/([a-z]+(?: or [a-z]+)?)\b", doc):
    for leg in legs.split(" or "):
        if f"{base}/{leg}" not in webhooks:
            problems.append(f"webhook {base}/{leg} is not in the n8n workflow files")

schema = json.loads(pathlib.Path("contracts/activity-event.schema.json").read_text())
kinds = set()
for definition in schema["$defs"].values():
    kind = definition.get("properties", {}).get("kind", {})
    if "const" in kind and "summary" in definition.get("properties", {}):
        kinds.add(kind["const"])
if len(kinds) < 20:
    problems.append(f"found only {len(kinds)} event kinds in the schema, so the check cannot be trusted")

blocks = re.findall(r"```mermaid\n(.*?)```", doc, re.S)
corpus = "\n".join(
    p.read_text()
    for d in ("platform-api/src", "agent-runtime/src", "contracts", "deploy", "infra", ".github/workflows")
    for p in pathlib.Path(d).rglob("*")
    if p.is_file() and p.suffix in {".py", ".json", ".yaml", ".yml", ".sh", ".tf", ".sql"}
)
# Alembic names the column of its own version table. No file of ours does.
corpus += "\nversion_num"
snake = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")
for block in blocks:
    for line in block.splitlines():
        streamed = re.search(r"events:|agent-events:|--\)P:", line)
        tail = line.split("events:", 1)[-1] if "events:" in line else line.split(":", 1)[-1]
        for token in snake.findall(tail if streamed else ""):
            if token not in kinds:
                problems.append(f"{token} is shown as an activity event but is not a kind in the schema")
        for token in snake.findall(line):
            if token not in kinds and not re.search(rf"\b{re.escape(token)}\b", corpus):
                problems.append(f"{token} appears in a diagram but nowhere in the code or contracts")

# Every table the migrations leave in place, and each schema's Alembic version table, is in an ER diagram.
migrations = pathlib.Path("platform-api/src/platform_api/migrations")
tables = set()
for schema in sorted(p for p in migrations.iterdir() if (p / "versions").is_dir()):
    tables.add(f"{schema.name}.alembic_version")
    for version in sorted((schema / "versions").glob("*.py")):
        upgrade = version.read_text().split("def downgrade", 1)[0]
        tables |= set(re.findall(r"CREATE TABLE (\w+\.\w+)", upgrade))
        tables -= set(re.findall(r"DROP TABLE (\w+\.\w+)", upgrade))
er = "\n".join(block for block in blocks if block.lstrip().startswith("erDiagram"))
drawn = set(re.findall(r'\["(\w+\.\w+)"\]', er))
for table in sorted(tables - drawn):
    problems.append(f"the table {table} is in the migrations but in no ER diagram")
for table in sorted(drawn - tables):
    problems.append(f"an ER diagram shows {table}, which the migrations do not leave in place")
if len(tables) < 20:
    problems.append(f"found only {len(tables)} tables in the migrations, so the check cannot be trusted")

# Every job in .github/workflows/ is in the CI/CD diagram as "job <id>", in the file's order.
cicd = "\n".join(blocks)
jobs = 0
for workflow in sorted(pathlib.Path(".github/workflows").glob("*.yml")):
    names = re.findall(r"^  ([A-Za-z0-9_-]+):\s*$", workflow.read_text().split("\njobs:\n", 1)[1], re.M)
    jobs += len(names)
    at = [cicd.find(f"job {name}<") for name in names]
    for name, where in zip(names, at):
        if where < 0:
            problems.append(f"job {name} in {workflow.name} is not in the CI/CD diagram")
    found = [where for where in at if where >= 0]
    if found != sorted(found):
        problems.append(f"the jobs of {workflow.name} are not in the file's order in the CI/CD diagram")

banned = ["Flint", "Forge", "Striker", "Spark Map", "Scout", "Analyst", "Messenger", "Clerk", "Fixer", "Kindling", "Firebreak", "Ember"]
# The names the rebuild retired (GLOSSARY.md).
banned += ["Room lead", "room_lead", "Release checker", "release_checker", "release_check", "release-check"]
for name in banned:
    if re.search(rf"\b{name}\b", doc, re.I):
        problems.append(f"the banned name {name} appears")
for dash, label in (("—", "em dash"), ("–", "en dash")):
    if dash in doc:
        problems.append(f"the file has an {label}")

for problem in sorted(set(problems)):
    print(f"FAIL: {problem}", file=sys.stderr)
print(f"checked {len(blocks)} diagrams, {len(kinds)} event kinds, {len(tables)} tables and {jobs} jobs")
sys.exit(1 if problems else 0)
PY

if [ "$status" -eq 0 ]; then
  echo "PASS"
else
  echo "FAIL"
fi
exit "$status"
