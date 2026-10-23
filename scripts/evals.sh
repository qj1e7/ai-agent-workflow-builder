#!/usr/bin/env bash
# The model bake-off. Scores every configured model on the golden set in agent-runtime/evals/cases/.
# Needs Docker and nothing else. Prints a results table and writes agent-runtime/evals/out/results.json.
#
# A provider runs only when its settings are set in this shell. The script passes them by name, so
# their values never appear on the command line or in the output. See docs/evidence/model-bakeoff/.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

image="${EVALS_IMAGE:-wab-evals:local}"
out="agent-runtime/evals/out"

# Ollama on the developer's machine, unless the caller set OLLAMA_BASE_URL, even to empty.
export OLLAMA_BASE_URL="${OLLAMA_BASE_URL-http://host.docker.internal:11434}"

settings=(
  OLLAMA_BASE_URL OLLAMA_MODELS
  AZURE_OPENAI_API_KEY AZURE_OPENAI_ENDPOINT AZURE_OPENAI_API_VERSION AZURE_OPENAI_DEPLOYMENTS
  ANTHROPIC_API_KEY ANTHROPIC_MODELS
  GOOGLE_API_KEY GOOGLE_MODELS
  EVAL_TEMPERATURE EVAL_JUDGE
)
env_args=()
for name in "${settings[@]}"; do
  if [ -n "${!name:-}" ]; then
    env_args+=(--env "$name")
  fi
done

cleanup() {
  if [ "${EVALS_KEEP_IMAGE:-0}" != "1" ]; then
    docker image rm "$image" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

echo "Building the eval image $image."
docker build --quiet --target evals --tag "$image" agent-runtime >/dev/null

mkdir -p "$out"
# The container runs as nobody and writes the results here.
chmod a+rwx "$out"

docker run --rm --name "wab-evals-$$" \
  --add-host host.docker.internal:host-gateway \
  --volume "$root/contracts:/contracts:ro" \
  --volume "$root/$out:/app/evals/out:rw" \
  ${env_args[@]+"${env_args[@]}"} \
  "$image" --out /app/evals/out/results.json
echo "Results on the host: $out/results.json"
