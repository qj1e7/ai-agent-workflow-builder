import httpx, time
from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.config import get_stream_writer
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

URL = "https://api.github.com/repos/langchain-ai/does-not-exist-xyz/releases?per_page=5"
class S(TypedDict, total=False):
    last_known_tag: str
    releases: list
    new: list
    summary: str

def fetch_releases(s):
    w = get_stream_writer()
    w({"type": "step_started", "step": "fetch_releases"})
    r = httpx.get(URL, headers={"Accept": "application/vnd.github+json"}, timeout=20)
    r.raise_for_status()
    rel = [{k: x.get(k) for k in ("tag_name", "name", "published_at", "prerelease", "draft", "html_url")} for x in r.json()]
    w({"type": "step_finished", "step": "fetch_releases", "result": {"count": len(rel)}})
    return {"releases": rel}

def find_new(s):
    w = get_stream_writer()
    w({"type": "step_started", "step": "find_new"})
    tags = [x["tag_name"] for x in s["releases"] if not x["draft"] and not x["prerelease"]]
    last = s.get("last_known_tag")
    new = [x for x in s["releases"] if not x["draft"] and not x["prerelease"] and (last is None or x["tag_name"] != last)]
    if last in tags:
        new = [x for x in s["releases"][: tags.index(last)] if not x["draft"] and not x["prerelease"]]
    w({"type": "step_finished", "step": "find_new", "result": {"new_count": len(new), "tags": [x["tag_name"] for x in new]}})
    return {"new": new}

def summarize(s):
    w = get_stream_writer()
    w({"type": "step_started", "step": "summarize"})
    m = GenericFakeChatModel(messages=iter([AIMessage(content=f"{len(s['new'])} new release(s): " + ", ".join(x['tag_name'] for x in s['new']))]))
    out = m.invoke("summarize").content
    w({"type": "step_finished", "step": "summarize", "result": {"summary": out}})
    return {"summary": out}

g = StateGraph(S)
g.add_node("fetch_releases", fetch_releases); g.add_node("find_new", find_new); g.add_node("summarize", summarize)
g.add_edge(START, "fetch_releases"); g.add_edge("fetch_releases", "find_new"); g.add_edge("find_new", "summarize"); g.add_edge("summarize", END)
app = g.compile()
