#!/usr/bin/env bash
# Renders every Mermaid block in docs/design/diagrams.md to a PNG in docs/evidence/diagrams/, which proves each one parses.
# Then checks the routes, event kinds and identifiers in the file against the contracts and the code.
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

cat > "$work/config.json" <<'JSON'
{"theme": "default", "flowchart": {"useMaxWidth": false}, "sequence": {"useMaxWidth": false}}
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
for route in sorted(set(re.findall(r"(?<![a-z/])(/v1/[a-z]+)", doc))):
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
    for d in ("platform-api/src", "agent-runtime/src", "contracts", "deploy")
    for p in pathlib.Path(d).rglob("*")
    if p.is_file() and p.suffix in {".py", ".json", ".yaml", ".sh"}
)
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

banned = ["Flint", "Forge", "Striker", "Spark Map", "Scout", "Analyst", "Messenger", "Clerk", "Fixer", "Kindling", "Firebreak", "Ember"]
for name in banned:
    if re.search(rf"\b{name}\b", doc, re.I):
        problems.append(f"the banned name {name} appears")
for dash, label in (("—", "em dash"), ("–", "en dash")):
    if dash in doc:
        problems.append(f"the file has an {label}")

for problem in sorted(set(problems)):
    print(f"FAIL: {problem}", file=sys.stderr)
print(f"checked {len(blocks)} diagrams and {len(kinds)} event kinds")
sys.exit(1 if problems else 0)
PY

if [ "$status" -eq 0 ]; then
  echo "PASS"
else
  echo "FAIL"
fi
exit "$status"
