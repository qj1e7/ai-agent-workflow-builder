"""PROTOTYPE, throwaway. Runs inside the platform-api container, so the AI key saved in the Portal
is opened there and never leaves it. Prints the results as JSON on stdout, progress on stderr."""

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import httpx
import psycopg
from psycopg.rows import dict_row

from cards import (CARD_SCHEMA, CHOICE_SCHEMA, CHOOSE_SYSTEM, DRAFT_SYSTEM, card_for_choice,
                   check_card, check_choice, compare_cards, compare_choices)
from platform_api.orchestration.model_settings import KeyBox

GATEWAY_HOST = "llm-gateway.aisg.sg"


def progress(text: str) -> None:
    print(text, file=sys.stderr, flush=True)


def saved_model() -> tuple[str, str, str]:
    with psycopg.connect(os.environ["DATABASE_URL_ORCHESTRATION"], row_factory=dict_row) as conn:
        row = conn.execute(
            "SELECT style, base_url, model, sealed_key FROM orchestration.model_setting WHERE slot = 'active'"
        ).fetchone()
    if row is None or row["style"] != "anthropic" or urlsplit(row["base_url"]).hostname != GATEWAY_HOST:
        sys.exit("The prototype only calls the AI Singapore gateway, and that is not the saved model")
    key = KeyBox(os.environ["SETTINGS_ENCRYPTION_KEY"]).open(row["sealed_key"])
    if key is None:
        sys.exit("The saved AI key no longer opens")
    return row["base_url"].rstrip("/"), row["model"], key


class Model:
    def __init__(self) -> None:
        self.base_url, self.name, key = saved_model()
        self._client = httpx.Client(
            timeout=120, headers={"x-api-key": key, "anthropic-version": "2023-06-01"}
        )

    def messages(self, body: dict[str, Any]) -> dict[str, Any]:
        """One raw call, retried once after a short wait. Raises when it still fails."""
        for attempt in (1, 2):
            response = self._client.post(f"{self.base_url}/v1/messages", json={"model": self.name, **body})
            if response.status_code in (429, 500, 502, 503, 504) and attempt == 1:
                time.sleep(3)
                continue
            if response.status_code != 200:
                raise RuntimeError(f"HTTP {response.status_code}: {response.text[:300]}")
            return response.json()
        raise RuntimeError("no answer")

    def fill(self, system: str, text: str, tool: str, schema: dict[str, Any]) -> dict[str, Any]:
        body = {
            "model": self.name,
            "max_tokens": 3000,
            "system": system,
            "messages": [{"role": "user", "content": text}],
            "tools": [{"name": tool, "description": "Save your answer.", "input_schema": schema}],
            "tool_choice": {"type": "tool", "name": tool},
        }
        started = time.monotonic()
        for attempt in (1, 2):
            try:
                response = self._client.post(f"{self.base_url}/v1/messages", json=body)
                if response.status_code in (429, 500, 502, 503, 504) and attempt == 1:
                    time.sleep(3)
                    continue
                if response.status_code != 200:
                    return {"error": f"HTTP {response.status_code}: {response.text[:300]}"}
                data = response.json()
                answer = next(b["input"] for b in data["content"] if b["type"] == "tool_use")
                usage = data.get("usage", {})
                return {"answer": answer, "seconds": round(time.monotonic() - started, 1),
                        "tokens": [usage.get("input_tokens"), usage.get("output_tokens")]}
            except (httpx.HTTPError, StopIteration, KeyError, ValueError) as error:
                if attempt == 1:
                    time.sleep(3)
                    continue
                return {"error": f"{type(error).__name__}: {str(error)[:300]}"}
        return {"error": "no answer"}


def draft(model: Model, task: str) -> dict[str, Any]:
    result = model.fill(DRAFT_SYSTEM, task, "save_agent_card", CARD_SCHEMA)
    if "answer" in result:
        result["checks"] = check_card(result["answer"])
    return result


def choose(model: Model, task: str, saved: list[dict[str, Any]]) -> dict[str, Any]:
    library = "\n".join(card_for_choice(card) for card in saved) or "(no agents saved yet)"
    text = f"Saved agents:\n{library}\n\nThe staff member's task:\n{task}"
    result = model.fill(CHOOSE_SYSTEM, text, "choose_agents", CHOICE_SCHEMA)
    if "answer" in result:
        result["checks"] = check_choice(result["answer"], [card["name"] for card in saved])
    return result


def one_round(model: Model, tasks: dict[str, Any], label: str) -> dict[str, Any]:
    """Drafts every agent, then lets the Room lead choose among this round's own saved agents."""
    drafts = []
    for n, item in enumerate(tasks["drafts"], 1):
        progress(f"{label}: drafting agent {n} of {len(tasks['drafts'])}")
        drafts.append(draft(model, item["task"]))
    saved = [d["answer"] for d in drafts if d.get("answer", {}).get("can_do")]
    choices = []
    for n, item in enumerate(tasks["choices"], 1):
        progress(f"{label}: Room lead choice {n} of {len(tasks['choices'])}")
        choices.append(choose(model, item["task"], saved))
    return {"drafts": drafts, "choices": choices, "saved": saved}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("tasks")
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--try", dest="tries", action="append", default=[])
    args = parser.parse_args()
    with open(args.tasks) as file:
        tasks = json.load(file)
    model = Model()
    with ThreadPoolExecutor(args.rounds) as pool:
        rounds = list(pool.map(lambda r: one_round(model, tasks, f"Run {r + 1}"), range(args.rounds)))

    def paired(kind: str, compare: Any) -> list[dict[str, Any]]:
        items = []
        for n, item in enumerate(tasks[kind]):
            runs = [r[kind][n] for r in rounds]
            answers = [run.get("answer") for run in runs]
            diff = compare(*answers[:2]) if len(runs) > 1 and all(answers[:2]) else None
            items.append({**item, "runs": runs, "diff": diff})
        return items

    out: dict[str, Any] = {"model": model.name, "ran_at": datetime.now(UTC).isoformat(),
                           "rounds": args.rounds, "drafts": paired("drafts", compare_cards),
                           "choices": paired("choices", compare_choices), "tries": []}
    saved = rounds[0]["saved"]

    for n, task in enumerate(args.tries, 1):
        progress(f"Your task {n} of {len(args.tries)}: Room lead choosing")
        tried: dict[str, Any] = {"task": task, "choice": choose(model, task, saved)}
        if tried["choice"].get("answer", {}).get("decision") == "new_agent":
            progress(f"Your task {n}: drafting a new agent")
            tried["draft"] = draft(model, task)
        out["tries"].append(tried)

    json.dump(out, sys.stdout, indent=1)


if __name__ == "__main__":
    main()
