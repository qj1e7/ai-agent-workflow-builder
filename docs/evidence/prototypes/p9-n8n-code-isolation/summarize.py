"""Reads raw/<variant>.json and prints the README's two tables as Markdown (python3 summarize.py > raw/summary.md).

The code table shows the variants that change where or how code runs; the disk table shows the ones that
change file access. Each table ends with a line that says whether every variant it leaves out gave the
same cells as `internal`.
"""

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ALL = ["internal", "external", "internal-escape", "external-escape", "deprecated-allowed", "ssrf-on",
       "files-block-off", "files-restrict-empty", "files-restrict-n8n", "files-restrict-n8n-block-off"]
CODE_VARIANTS = ALL[:6]
DISK_VARIANTS = ["internal", "external", "files-block-off", "files-restrict-empty", "files-restrict-n8n", "files-restrict-n8n-block-off"]
N8N = ["ENCKEY", "DBPASS", "NODEKEY", "STARTSECRET", "IDHEADER"]
BLOCKS = {
    "read_write_file": "Read/Write Files from Disk", "read_binary_file": "Read Binary File", "read_binary_files": "Read Binary Files",
    "write_binary_file": "Write Binary File", "git_status": "Git, status", "git_clone_from": "Git, clone from",
    "git_clone_into": "Git, clone into", "execute_sub_workflow_file": "Execute Sub-workflow, from a file",
}
TARGETS = {
    "n8n_config": "`~/.n8n/config`", "proc_self_environ": "`/proc/self/environ`", "proc_1_environ": "`/proc/1/environ`",
    "outside": "a file outside both folders", "allowed_folder": "`~/.n8n-files`", "link_to_n8n_config": "a symlink to `~/.n8n/config`",
    "n8n_custom_folder": "`~/.n8n/custom`", "n8n_folder": "`~/.n8n`",
}


def load(v):
    p = os.path.join(HERE, "raw", f"{v}.json")
    return json.load(open(p)) if os.path.exists(p) else None


def walk(d):
    """Every dict inside d, d included."""
    if isinstance(d, dict):
        yield d
        for v in d.values():
            yield from walk(v)


def js_cell(entry, record, tag):
    if entry is None:
        return "not run"
    if "workflow_not_run" in entry:
        return "refused by n8n"
    if "error_class" in entry and "result" not in entry:
        return entry["error_class"]
    if not entry.get("ran"):
        return "did not run"
    r = entry.get("result") or {}
    found = {k: v for k, v in r.items() if k != "identity"}
    n8n = any(d.get(n) for d in walk(found) for n in N8N)
    config = any(d.get("ENCKEY") for d in walk({"f": r.get("files", {}).get("n8n_config", {}), "h": r.get("helper_files", {}).get("n8n_config", {})}))
    token = any(d.get("RUNNERTOKEN") for d in walk(found))
    ident = r.get("identity") or {}
    statuses = [v for k, v in ident.items() if k.endswith("no_header")]
    reached = any(s and s != 0 for s in statuses) or bool((record.get(f"{tag}-helper-noheader") or {}).get("requests"))
    got = any(v == 200 for k, v in ident.items() if k.endswith("with_header"))
    why = [v for k, v in ident.items() if k.startswith("helper") and k.endswith("_failed")]
    return ", ".join([
        "env " + ("YES" if n8n else "no"),
        "config " + ("YES" if config else "no"),
        "runner token " + ("YES" if token else "no"),
        "identity " + ("200" if got else "400" if reached else "not reached" + (f" ({why[0]})" if why else "")),
    ])


def py_cell(e):
    if "error_class" in e:
        return e["error_class"]
    if not e.get("ran"):
        return "did not run"
    r = e.get("result") or {}
    return ("ran, env " + ("YES" if any(d.get(n) for d in walk(r) for n in N8N) else "no")
            + ", runner token " + ("YES" if any(d.get("RUNNERTOKEN") for d in walk(r)) else "no")
            + (", `open` refused" if r.get("open_refused") else ""))


def code_rows(data, v):
    rec = {k[len(v) + 1:]: x for k, x in (data[v].get("identity_record") or {}).items() if k.startswith(v + "-")}
    cb = data[v]["code_blocks"]
    agent = data[v].get("agent") or {}
    rows = {}
    for name, key, tag in [("Code (JavaScript)", "code_js", "code-js"), ("AI Transform", "ai_transform", "ai-transform"),
                           ("Sort, code mode", "sort_code", "sort"), ("Item Lists, code sort", "item_lists_code", "item-lists"),
                           ("Function", "function", "function"), ("Function Item", "function_item", "function-item"),
                           ("LangChain Code", "langchain_code", "langchain-code")]:
        rows[name] = js_cell(cb.get(key), rec, tag)
    rows["Code Tool (JavaScript), called by an AI Agent"] = js_cell(agent.get("JS tool"), rec, "code-tool-js")
    for kind, label in (("plain", "no import, `open()`"), ("import_os", "`import os`"), ("dunder", "`__subclasses__`")):
        rows[f"Code (Python), {label}"] = py_cell(cb.get(f"code_python_{kind}") or {})
    rows["Code Tool (Python), no import, `open()`"] = py_cell(agent.get("Python tool") or {})
    for q in ("control", "allowed_folder", "n8n_config", "proc_self_environ", "url"):
        e = cb.get(f"merge_sql_{q}") or {}
        hit = any((e.get("output_scan") or {}).get(n) for n in N8N)
        rows[f"Merge, SQL `{q}`"] = (e.get("error_class") or f"{e.get('rows', 0)} row(s)") + ("; CANARY" if hit else "")
    e = cb.get("http_request_control") or {}
    rows["HTTP Request to the identity endpoint, no header"] = e.get("error_class") or str((e.get("result") or {}).get("statusCode"))
    return rows


def disk_rows(data, v):
    rows = {}
    for label, e in data[v]["disk"].items():
        parts = label.split(":")
        name = f"{BLOCKS[parts[0]]}, {parts[1] + ' ' if len(parts) == 3 else ''}{TARGETS[parts[-1]]}"
        if "file_written" in e:
            cell = "WROTE" if e["file_written"] else (e.get("error_class") or "not written")
        elif e.get("read"):
            c = e.get("content") or {}
            hits = [n for n in N8N + ["RUNNERTOKEN"] if c.get(n)]
            marks = [k.replace("_marker", "") for k in ("encryptionKey_marker", "control_marker", "outside_marker") if c.get(k)]
            cell = "READ" + (" " + ", ".join(hits) if hits else "") + (" (" + ", ".join(marks) + " marker)" if marks else "")
        else:
            cell = e.get("error_class") or "?"
        rows[name] = cell
    return rows


def table(data, shown, rows_of):
    present = [v for v in shown if data.get(v)]
    per = {v: rows_of(data, v) for v in present}
    print("| Block | " + " | ".join(f"`{v}`" for v in present) + " |")
    print("|---|" + "---|" * len(present))
    for name in per[present[0]]:
        print(f"| {name} | " + " | ".join(per[v].get(name, "not run") for v in present) + " |")
    left_out = [v for v in ALL if v not in shown and data.get(v)]
    same = [v for v in left_out if rows_of(data, v) == per["internal"]]
    differ = [v for v in left_out if v not in same]
    print()
    print(f"Left out, and the same as `internal` in every row: {', '.join(f'`{v}`' for v in same) or 'none'}."
          + (f" Left out, and different: {', '.join(f'`{v}`' for v in differ)}." if differ else ""))


def main():
    data = {v: load(v) for v in ALL}
    table(data, CODE_VARIANTS, code_rows)
    print()
    table(data, DISK_VARIANTS, disk_rows)


if __name__ == "__main__":
    main()
