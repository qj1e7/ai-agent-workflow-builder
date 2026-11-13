"""Restarts n8n once per setting and reruns the questions that depend on it. Run after run.sh; takes a while on a busy host."""

import json
import os
import subprocess
import time
import urllib.request

from lib import B, HERE, compose

OURS = ["startFromPortal", "callOurApi", "askForYes", "reportFailure"]
N8N = ["n8n-nodes-base.scheduleTrigger", "n8n-nodes-base.manualTrigger", "n8n-nodes-base.errorTrigger", "n8n-nodes-base.if",
       "n8n-nodes-base.merge", "n8n-nodes-base.noOp", "n8n-nodes-base.stickyNote"]


def allow(prefix):
    return json.dumps([f"{prefix}.{n}" for n in OURS] + N8N)


PRUNE = {"P7_PRUNE": "true", "P7_PRUNE_MAX_COUNT": "2", "P7_PRUNE_INTERVAL": "1"}
VARIANTS = [
    ("throw", {"P7_ASK_REFUSE": "throw"}, ["q06"], ("compose.yaml",)),
    ("guard_off", {"P7_GUARD_OFF": "1"}, ["q06", "q17"], ("compose.yaml",)),
    ("wab_names", {"P7_NODES_INCLUDE": allow("wab")}, ["q11"], ("compose.yaml",)),
    ("package", {"P7_NODES_INCLUDE": allow("n8n-nodes-wab")}, ["q11"], ("compose.yaml", "compose.package.yaml")),
    ("custom", {"P7_NODES_INCLUDE": allow("CUSTOM"), **PRUNE}, ["q11", "q16"], ("compose.yaml",)),
]


def ready(timeout=900):
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urllib.request.urlopen(B + "/healthz/readiness", timeout=5) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(5)
    return False


only = os.environ.get("P7_ONLY")
for name, extra, scripts, files in VARIANTS:
    if only and name != only:
        continue
    print(f"== variant {name}", flush=True)
    compose("up", "-d", "--force-recreate", "--no-deps", "n8n", env_extra=extra, files=files)
    assert ready(), f"n8n did not come back for {name}"
    for q in scripts:
        script = next(f for f in sorted(os.listdir(HERE)) if f.startswith(q + "_"))
        subprocess.run(["python3", script], cwd=HERE, env=dict(os.environ, P7_VARIANT=name, **extra), check=False)
