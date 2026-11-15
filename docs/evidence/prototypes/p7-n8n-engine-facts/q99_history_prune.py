"""Q7's second half: run at least an hour after n8n last started. Is the version q07 backdated by 30 hours gone,
while the draft and the published versions stay?
"""

import time

from lib import Raw, compose, psql

raw = Raw("q99")
wid, v2, at = open("raw/q07_backdated.txt").read().split()
raw("minutes since q07 backdated v2", round((time.time() - float(at)) / 60))
raw("n8n container started at", compose("ps", "--format", "{{.Name}} {{.RunningFor}}").stdout.strip().splitlines())
raw("workflow_history rows now (versionId, createdAt)", psql(f"select \"versionId\", \"createdAt\" from workflow_history where \"workflowId\" = '{wid}' order by \"createdAt\"").splitlines())
raw("the backdated v2 still there?", bool(psql(f"select 1 from workflow_history where \"versionId\" = '{v2}'")))
raw("draft and published ids", psql(f"select \"versionId\", \"activeVersionId\" from workflow_entity where id = '{wid}'"))
