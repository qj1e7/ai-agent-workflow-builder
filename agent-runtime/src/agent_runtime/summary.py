import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

from agent_runtime.contract import Finding

log = logging.getLogger(__name__)

MAX_SUMMARY_LENGTH = 300
# The summary model gets one try of at most this long, then the template answers instead.
SUMMARY_TIMEOUT_SECONDS = 10

type ModelFactory = Callable[[str], BaseChatModel]


@dataclass(frozen=True)
class Checked:
    name: str
    finding: Finding


class Summarizer(Protocol):
    def summarise(self, repo: str, last_known_tag: str, new_tags: Sequence[str]) -> str: ...

    def summarise_check(self, checked: Sequence[Checked]) -> str: ...


def summary_prompt(repo: str, last_known_tag: str, new_tags: Sequence[str]) -> str:
    return (
        f"Write one plain sentence for non-technical support staff. Say which new releases "
        f"of the project {repo} appeared after {last_known_tag}. The new release tags are: "
        f"{', '.join(new_tags)}. Reply with the sentence only."
    )


def check_prompt(checked: Sequence[Checked]) -> str:
    lines = "\n".join(f"- {item.name}: {_result_of(item.finding)}" for item in checked)
    return (
        "Write one plain sentence for non-technical support staff about this check of watched "
        "software. Say which software have new releases and which could not be checked. Only "
        f"use what is listed. The results are:\n{lines}\nReply with the sentence only."
    )


def _result_of(finding: Finding) -> str:
    match finding.state:
        case "behind" | "already_raised":
            count = len(finding.new_versions)
            noun = "release" if count == 1 else "releases"
            return f"{count} new {noun}, the newest is {finding.newest}"
        case "cant_check":
            return "could not be checked"
        case "starting_point" | "up_to_date":
            return "up to date"


def usable_summary(text: str) -> bool:
    return bool(text) and "\n" not in text and len(text) <= MAX_SUMMARY_LENGTH


def template_summary(new_tags: Sequence[str]) -> str:
    noun = "release" if len(new_tags) == 1 else "releases"
    return f"{len(new_tags)} new {noun}: {', '.join(new_tags)}"


def template_check_summary(checked: Sequence[Checked]) -> str:
    behind = [c for c in checked if c.finding.state == "behind"]
    raised = [c.name for c in checked if c.finding.state == "already_raised"]
    cannot = [c.name for c in checked if c.finding.state == "cant_check"]
    readable = len(checked) - len(cannot)
    if behind:
        news = _names_and([f"{c.name} {c.finding.newest}" for c in behind])
        verb = "has" if len(behind) == 1 else "have"
        sentence = f"{len(behind)} of {len(checked)} watched software {verb} new releases: {news}."
    elif raised:
        verb = "has a ticket" if len(raised) == 1 else "have tickets"
        sentence = f"No new tickets are needed, as {_names_and(raised)} already {verb}."
    elif cannot:
        sentence = f"All {readable} watched software we could read are up to date."
    else:
        sentence = f"All {len(checked)} watched software are up to date."
    return f"{sentence} {_names_and(cannot)} could not be checked." if cannot else sentence


def _names_and(names: Sequence[str]) -> str:
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


class TemplateSummarizer:
    def summarise(self, repo: str, last_known_tag: str, new_tags: Sequence[str]) -> str:
        return template_summary(new_tags)

    def summarise_check(self, checked: Sequence[Checked]) -> str:
        return template_check_summary(checked)


def model_factory(
    base_url: str | None = None, api_key: str | None = None, provider: str | None = None
) -> ModelFactory:
    pairs = (("base_url", base_url), ("api_key", api_key), ("model_provider", provider))
    gateway: dict[str, Any] = {key: value for key, value in pairs if value}

    def build(name: str) -> BaseChatModel:
        # Naming configurable_fields picks the overload that returns a plain chat model.
        return init_chat_model(
            name,
            configurable_fields=None,
            timeout=SUMMARY_TIMEOUT_SECONDS,
            max_retries=0,
            **gateway,
        )

    return build


default_model_factory = model_factory()


class ModelSummarizer:
    def __init__(
        self,
        model_name: str,
        factory: ModelFactory = default_model_factory,
        fallback: Summarizer | None = None,
    ) -> None:
        self._model_name = model_name
        self._factory = factory
        self._fallback = fallback or TemplateSummarizer()

    def summarise(self, repo: str, last_known_tag: str, new_tags: Sequence[str]) -> str:
        prompt = summary_prompt(repo, last_known_tag, new_tags)
        return self._answer(prompt) or self._fallback.summarise(repo, last_known_tag, new_tags)

    def summarise_check(self, checked: Sequence[Checked]) -> str:
        return self._answer(check_prompt(checked)) or self._fallback.summarise_check(checked)

    def _answer(self, prompt: str) -> str | None:
        try:
            text = self._factory(self._model_name).invoke(prompt).text.strip()
        except Exception:
            log.warning("summary model failed, using the template", exc_info=True)
            return None
        if not usable_summary(text):
            log.warning("summary model gave an unusable answer, using the template")
            return None
        return text
