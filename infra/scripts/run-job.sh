#!/bin/sh
# Starts a Container Apps Job and waits until it ends. Needs an az CLI that is signed in.
# Usage: infra/scripts/run-job.sh <resource-group> <job-name> [timeout-seconds]
set -eu

group=$1
job=$2
timeout=${3:-900}

execution=$(az containerapp job start --resource-group "$group" --name "$job" --query name --output tsv)
echo "$job: started execution $execution"

deadline=$(($(date +%s) + timeout))
while :; do
  status=$(az containerapp job execution show --resource-group "$group" --name "$job" \
    --job-execution-name "$execution" --query properties.status --output tsv)
  case $status in
    Succeeded)
      echo "$job: succeeded"
      exit 0
      ;;
    Failed | Stopped | Degraded)
      echo "$job: $status. Its logs are in Log Analytics, table ContainerAppConsoleLogs_CL." >&2
      exit 1
      ;;
  esac
  if [ "$(date +%s)" -ge "$deadline" ]; then
    echo "$job: still $status after ${timeout}s" >&2
    exit 1
  fi
  sleep 10
done
