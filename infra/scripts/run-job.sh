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
# A status check can fail while the execution is fine, for example when Azure answers 503. Allow
# 5 failed checks in a row. Starting the job is not retried, because a retry could start a second
# execution.
poll_failures=0
while :; do
  if status=$(az containerapp job execution show --resource-group "$group" --name "$job" \
    --job-execution-name "$execution" --query properties.status --output tsv); then
    poll_failures=0
  else
    poll_failures=$((poll_failures + 1))
    if [ "$poll_failures" -ge 5 ]; then
      echo "$job: could not read the status of execution $execution after 5 tries in a row" >&2
      exit 1
    fi
    echo "$job: status check failed ($poll_failures of 5), trying again" >&2
    sleep 10
    continue
  fi
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
