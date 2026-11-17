"""Runs spike P9: for each variant, boots the throwaway stack, runs every probe through n8n's own
execution, and writes raw/<variant>.json and raw/<variant>.txt.

Usage: python3 run.py [variant ...]    (no names runs them all)
       python3 run.py down             (removes every p9 container, network and volume)
"""

import ast
import json
import re
import sys
import time

import probes
from lib import B, Raw, _send, clean_up, compose, fake, in_n8n, make_env, node_result, public, run_by_hand, setup_owner

VARIANTS = [
    "internal", "external", "internal-escape", "external-escape",
    "files-block-off", "files-restrict-empty", "files-restrict-n8n", "files-restrict-n8n-block-off",
    "ssrf-on", "deprecated-allowed",
]
WRITE = "require('fs').writeFileSync(process.argv[1], process.argv[2])"
TYPES_USED = [
    "n8n-nodes-base.code", "n8n-nodes-base.aiTransform", "n8n-nodes-base.function", "n8n-nodes-base.functionItem",
    "n8n-nodes-base.sort", "n8n-nodes-base.itemLists", "n8n-nodes-base.merge", "n8n-nodes-base.httpRequest",
    "@n8n/n8n-nodes-langchain.code", "@n8n/n8n-nodes-langchain.toolCode", "@n8n/n8n-nodes-langchain.agent",
    "@n8n/n8n-nodes-langchain.lmChatOpenAi", "n8n-nodes-base.readWriteFile", "n8n-nodes-base.readBinaryFile",
    "n8n-nodes-base.readBinaryFiles", "n8n-nodes-base.writeBinaryFile", "n8n-nodes-base.git", "n8n-nodes-base.executeWorkflow",
    "n8n-nodes-base.executeCommand", "n8n-nodes-base.localFileTrigger",
]


def category(message: str) -> str:
    """n8n's error, as a class. The message itself is never saved."""
    m = message or ""
    rules = [
        ("blocked by n8n's SSRF protection", r"restricted IP address|SsrfBlocked"),
        ("blocked by n8n", r"not allowed|outside the allowed file paths|inside n8n's own directories|Symlinks are not allowed"),
        ("refused before running", r"[Ss]ecurity violation|is disallowed|not allowed to|forbidden"),
        ("python runner unavailable", r"[Pp]ython runner|runner .*unavailable|Python 3 is missing|virtual environment"),
        ("not found", r"No file\(s\) found|could not be found|ENOENT|no such file"),
        ("read, but not a workflow", r"not valid JSON"),
        ("not a git repository", r"not a git repository|does not appear to be a git repository|repository .* does not exist|Could not determine the git repository"),
        ("os refused", r"EACCES|[Pp]ermission denied|EPERM"),
        ("unknown block", r"Unrecognized node type|install this node"),
        ("timed out", r"[Tt]imed? ?out"),
        ("refused by the SQL sandbox", r"Network and file system access is disabled in the SQL sandbox"),
        ("sql error", r"[Pp]arse error|alasql|SQL"),
    ]
    for name, pattern in rules:
        if re.search(pattern, m):
            return name
    return f"other error ({len(m)} chars)"


KINDS = {"connection refused", "blocked by n8n", "timed out", "other"}


def bools(value):
    """Keeps a probe's own answer: booleans, numbers, the probe's fixed error kinds, and the dicts
    around them. Any other text is dropped."""
    if isinstance(value, dict):
        return {k: bools(v) for k, v in value.items()
                if isinstance(v, (bool, int, float, dict)) or v is None or (isinstance(v, str) and v in KINDS)}
    return value


def scan_text(text: str) -> dict:
    r = {n: f"P9CANARY-{n}" in text for n in probes.NAMES}
    r.update({k: m in text for k, m in probes.MARKERS.items()})
    return r


def up(variant: str, raw: Raw) -> None:
    compose("down", "--remove-orphans", variant="external", check=False)
    p = compose("up", "-d", "--wait", "--wait-timeout", "240", variant=variant, check=False)
    raw("compose up", {"variant": variant, "exit": p.returncode})
    if p.returncode != 0:
        raise SystemExit(f"stack did not start for {variant}")
    for cmd in (
        ["mkdir", "-p", "/home/node/.n8n-files", "/home/node/.n8n/custom"],
        ["node", "-e", WRITE, "/home/node/.n8n-files/p9-control.txt", "P9MARKER-CONTROL"],
        ["node", "-e", WRITE, "/home/node/p9-outside.txt", "P9MARKER-OUTSIDE"],
        ["ln", "-sfn", "/home/node/.n8n/config", "/home/node/.n8n-files/p9-link"],
        ["rm", "-rf", "/home/node/.n8n-files/p9-clone", "/home/node/.n8n/custom/p9-clone", "/home/node/.n8n/custom/p9-marker.txt",
         "/home/node/p9-write-outside.txt", "/home/node/.n8n-files/p9-write.txt"],
    ):
        in_n8n(*cmd, variant=variant)
    names = in_n8n("ls", "-A", "/home/node/.n8n", variant=variant).stdout.split()
    raw("names in n8n's folder (names only)", sorted(names))
    fake("POST", "/p9/reset")


def run_code_blocks(variant, owner, raw):
    results = {}
    for label, nodes, conns, read_node, how in probes.code_blocks(f"{variant}-"):
        run, failed = run_by_hand(owner, f"p9 {label}", nodes, conns, read_node)
        if failed:
            results[label] = {"workflow_not_run": failed.get("create_failed") or failed.get("run_failed")}
            raw(label, results[label])
            continue
        r = node_result(run["data"], read_node)
        entry: dict = {"ran": r.get("ran", False)}
        if "error" in r:
            entry["error_class"] = category(r["error"] + " " + r.get("description", ""))
        else:
            j = r.get("json") or {}
            if how == "json":
                err = j.get("error") if isinstance(j, dict) else None
                if isinstance(err, str):
                    entry["error_class"] = category(err)
                elif isinstance(err, dict):
                    entry["error_class"] = category(f"{err.get('message') or ''} {err.get('description') or ''}")
                else:
                    entry["result"] = bools(j)
            elif how == "p9":
                if isinstance(j, dict) and isinstance(j.get("p9"), str):
                    entry["result"] = bools(json.loads(j["p9"]))
                elif isinstance(j, dict) and isinstance(j.get("error"), str):
                    entry["error_class"] = category(j["error"])
                else:
                    entry["result"] = None
            elif how == "scan":
                if isinstance(j, dict) and isinstance(j.get("error"), str):
                    entry["error_class"] = category(j["error"])
                runs = run["data"]["data"]["resultData"]["runData"].get(read_node) or []
                items = [i for r in runs for outs in (r.get("data") or {}).values() for o in outs or [] for i in o or []]
                entry["rows"] = sum(1 for i in items if not (i.get("json") or {}).get("error"))
                entry["output_scan"] = scan_text(json.dumps(items))
        results[label] = entry
        raw(label, entry)
        clean_up(run)
    return results


def run_agent(variant, raw):
    st, cred = public("POST", "/credentials", {"name": "p9 stand-in model", "type": "openAiApi",
                                               "data": {"apiKey": "p9-not-a-real-key", "url": "http://localhost:42356/v1", "header": False}})
    if st != 200:
        raw("agent: credential", {"created": False, "status": st})
        return {"credential_not_made": st}
    owner = setup_owner()
    nodes, conns = probes.agent_workflow(f"{variant}-", {"id": cred["id"], "name": cred["name"]})
    run, failed = run_by_hand(owner, "p9 agent", nodes, conns, "Agent")
    out: dict = {}
    if failed:
        out = {"workflow_not_run": failed.get("create_failed") or failed.get("run_failed")}
    else:
        agent = node_result(run["data"], "Agent")
        out["agent_ran"] = agent.get("ran", False)
        err = agent.get("error") if "error" in agent else (agent.get("json") or {}).get("error")
        if isinstance(err, dict):
            err = f"{err.get('message') or ''} {err.get('description') or ''}"
        if isinstance(err, str):
            out["agent_error_class"] = category(err)
        for tool, parse in (("JS tool", json.loads), ("Python tool", ast.literal_eval)):
            r = node_result(run["data"], tool)
            entry: dict = {"ran": r.get("ran", False)}
            if "error" in r:
                entry["error_class"] = category(r["error"])
            else:
                text = (r.get("json") or {}).get("response")
                try:
                    entry["result"] = bools(parse(text)) if isinstance(text, str) and text[:1] in "{[" else None
                except (ValueError, SyntaxError):
                    entry["result"] = None
                if entry["result"] is None and isinstance(text, str):
                    entry["error_class"] = category(text)
            out[tool] = entry
        clean_up(run)
    public("DELETE", f"/credentials/{cred['id']}")
    raw("agent with code tools", out)
    return out


def run_disk(variant, owner, raw):
    results = {}
    for label, nodes, conns in probes.disk_reads() + probes.other_disk():
        run, failed = run_by_hand(owner, f"p9 {label}", nodes, conns, nodes[-1]["name"])
        if failed:
            results[label] = {"workflow_not_run": failed.get("create_failed") or failed.get("run_failed")}
            raw(label, results[label])
            continue
        disk = node_result(run["data"], "Disk")
        entry: dict = {"ran": disk.get("ran", False)}
        if "error" in disk:
            entry["error_class"] = category(disk["error"] + " " + disk.get("description", ""))
        else:
            j = disk.get("json") or {}
            if isinstance(j, dict) and isinstance(j.get("error"), str):
                entry["error_class"] = category(j["error"])
            else:
                entry["read"] = True
        if any(n["name"] == "Scan" for n in nodes):
            scanned = node_result(run["data"], "Scan").get("json") or {}
            entry["content"] = {k: v for k, v in scanned.items() if isinstance(v, bool)}
        results[label] = entry
        raw(label, entry)
        clean_up(run)
    for label, path, nodes, conns in probes.disk_writes():
        run, failed = run_by_hand(owner, f"p9 {label}", nodes, conns, "Disk")
        disk = node_result(run["data"], "Disk") if run else {}
        entry = {"ran": disk.get("ran", False)}
        if failed:
            entry["workflow_not_run"] = failed.get("create_failed") or failed.get("run_failed")
        if "error" in disk:
            entry["error_class"] = category(disk["error"] + " " + disk.get("description", ""))
        elif isinstance((disk.get("json") or {}).get("error"), str):
            entry["error_class"] = category(disk["json"]["error"])
        entry["file_written"] = in_n8n("test", "-f", path, variant=variant).returncode == 0
        in_n8n("rm", "-f", path, variant=variant)
        results[label] = entry
        raw(label, entry)
        clean_up(run)
    return results


def types_loaded(owner, raw):
    st, types = _send(owner.op, "GET", B + "/types/nodes.json")
    names = {t["name"] for t in types} if st == 200 else set()
    loaded = {t: t in names for t in TYPES_USED}
    raw("block types n8n loads", {"total": len(names), **loaded})
    return {"total": len(names), **loaded}


def run_variant(variant):
    raw = Raw(variant)
    up(variant, raw)
    owner = setup_owner()
    raw.put("variant", variant)
    raw.put("types", types_loaded(owner, raw))
    raw.put("code_blocks", run_code_blocks(variant, owner, raw))
    raw.put("agent", run_agent(variant, raw))
    raw.put("disk", run_disk(variant, owner, raw))
    time.sleep(2)
    record = fake("GET", "/p9/record")
    identity = {k: v for k, v in (record.get("identity") or {}).items()}
    raw("identity endpoint record (per probe tag)", identity)
    raw("stand-in model calls", record.get("model_calls"))
    raw.put("identity_record", identity)
    raw.put("model_calls", record.get("model_calls"))
    raw.save()


if __name__ == "__main__":
    make_env()
    args = sys.argv[1:]
    if args == ["down"]:
        p = compose("down", "-v", "--remove-orphans", variant="external", check=False)
        print("down", p.returncode)
        sys.exit(0)
    for v in args or VARIANTS:
        assert v in VARIANTS, f"unknown variant {v}"
        print(f"== {v}")
        run_variant(v)
