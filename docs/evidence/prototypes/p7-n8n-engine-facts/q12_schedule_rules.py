"""Q12: what the Schedule Trigger's `rule` means, in n8n's own code, as a table E5's n8n_schedule.py can test against.

Also checks that n8n's hidden seconds and minutes ("stableInt") can be computed in Python.
"""

import hashlib
import json
import os

from lib import HERE, Raw, compose

raw = Raw("q12")
js = open(os.path.join(HERE, "cron_table.js")).read()
r = compose("exec", "-T", "n8n", "node", "-", check=False, input=js)
assert r.returncode == 0, r.stderr[-800:]
table = json.loads(r.stdout.strip().splitlines()[-1])
json.dump(table, open(os.path.join(HERE, "cron_table.json"), "w"), indent=1)
raw("cron library version, timezone, reference time, node key", [table["cron"], table["tz"], table["from"], table["node_key"]])
for row in table["rows"]:
    raw(row["label"], {"expression": row["expression"], "next_utc": row["next_utc"], "recurrence_filter": row["recurrence_filter"]})


def stable_int(seed: str, label: str, lo: int, hi: int) -> int:
    h = hashlib.sha256(f"{seed}:{label}".encode()).digest()
    return lo + int.from_bytes(h[:4], "big") % (hi - lo)


key = table["node_key"]
mine = {"second": stable_int(key, "second", 0, 60), "minute": stable_int(key, "minute", 0, 60), "hour": stable_int(key, "hour", 0, 24)}
theirs = table["rows"][2]["expression"].split()
raw("Python stableInt for this node key", mine)
raw("n8n's expression for 'daily, hour and minute left out'", theirs)
raw("Python matches n8n (second, minute, hour)", [mine["second"] == int(theirs[0]), mine["minute"] == int(theirs[1]), mine["hour"] == int(theirs[2])])
