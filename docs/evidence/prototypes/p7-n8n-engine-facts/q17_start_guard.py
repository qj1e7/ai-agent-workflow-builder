"""The control for Start from the Portal's guard: with P7_GUARD_OFF=1 a start with a bad signature must start a run,
which proves q01's "401, no execution" comes from the node's check and not from something else.
"""

import os
import time

from lib import B, Raw, call_node, create, executions, link, post_url, public, signed_start, start_node

variant = os.environ.get("P7_VARIANT", "respond")
raw = Raw(f"q17_{variant}")
w = create(f"q17 start guard ({variant})", [start_node(), call_node("Read release", "read")], link(("Start from the Portal", "Read release")), raw=raw)
wid, hook = w["id"], w["nodes"][0]["webhookId"]
public("POST", f"/workflows/{wid}/publish", {})
time.sleep(2)
body, _ = signed_start()
st, r = post_url(f"{B}/webhook/{hook}/start", headers={"x-wab-signature": "00" * 32}, raw_body=body)
raw(f"{variant}: start with a bad signature", [st, r])
time.sleep(8)
raw(f"{variant}: executions it made", [(e["id"], e["status"], e["mode"]) for e in executions(wid)])
public("POST", f"/workflows/{wid}/unpublish", {})
