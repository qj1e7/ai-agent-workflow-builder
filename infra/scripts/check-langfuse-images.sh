#!/bin/sh
# Checks that the Langfuse VM runs the images a laptop runs (ADR 0050): every image in the VM's
# compose template, pinned by digest, must appear with the same tag and digest in
# deploy/compose.yaml. Caddy is the one exception, because only the VM serves HTTPS.
# Usage: check-langfuse-images.sh <compose.yaml.tftpl> <deploy/compose.yaml>
set -eu

template=$1
compose=$2
azure_only=caddy

# Prints each image reference, without quotes and without the docker.io/ and library/ prefixes.
images() {
  sed -n 's/^[[:space:]]*image:[[:space:]]*//p' "$1" | tr -d "\"'" |
    sed 's|^docker\.io/||; s|^library/||'
}

failures=0
checked=0
for image in $(images "$template"); do
  repository=${image%%[:@]*}
  case $image in
    *@sha256:*) ;;
    *)
      echo "FAIL  $image in $template is not pinned by digest"
      failures=$((failures + 1))
      continue
      ;;
  esac
  [ "$repository" = "$azure_only" ] && continue
  checked=$((checked + 1))
  local_refs=$(images "$compose" | awk -v repository="$repository" '{ r = $0; sub(/[:@].*/, "", r) } r == repository')
  if [ -z "$local_refs" ]; then
    echo "FAIL  $repository is in the VM's compose file but not in $compose"
    failures=$((failures + 1))
  elif [ "$(printf '%s\n' "$local_refs" | sort -u)" != "$image" ]; then
    echo "FAIL  $repository differs: the VM runs $image, $compose has $(printf '%s' "$local_refs" | tr '\n' ' ')"
    failures=$((failures + 1))
  else
    echo "ok    $image"
  fi
done

if [ "$checked" = 0 ]; then
  echo "FAIL  no images found in $template"
  failures=$((failures + 1))
fi
if [ "$failures" != 0 ]; then
  echo "check-langfuse-images.sh: $failures problem(s)"
  exit 1
fi
echo "check-langfuse-images.sh: the VM's images match $compose"
