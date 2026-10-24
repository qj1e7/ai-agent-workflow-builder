import logging
from collections.abc import Callable, Sequence
from typing import Any, Protocol

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

log = logging.getLogger(__name__)

MAX_SUMMARY_LENGTH = 300
# The summary model gets one try of at most this long, then the template answers instead.
SUMMARY_TIMEOUT_SECONDS = 10

type ModelFactory = Callable[[str], BaseChatModel]


class Summarizer(Protocol):
    def summarise(self, repo: str, last_known_tag: str, new_tags: Sequence[str]) -> str: ...


def summary_prompt(repo: str, last_known_tag: str, new_tags: Sequence[str]) -> str:
    return (
        f"Write one plain sentence for non-technical support staff. Say which new releases "
        f"of the project {repo} appeared after {last_known_tag}. The new release tags are: "
        f"{', '.join(new_tags)}. Reply with the sentence only."
    )


def usable_summary(text: str) -> bool:
    return bool(text) and "\n" not in text and len(text) <= MAX_SUMMARY_LENGTH


def template_summary(new_tags: Sequence[str]) -> str:
    noun = "release" if len(new_tags) == 1 else "releases"
    return f"{len(new_tags)} new {noun}: {', '.join(new_tags)}"


class TemplateSummarizer:
    def summarise(self, repo: str, last_known_tag: str, new_tags: Sequence[str]) -> str:
        return template_summary(new_tags)


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
        try:
            text = self._ask(repo, last_known_tag, new_tags)
        except Exception:
            log.warning("summary model failed, using the template", exc_info=True)
            return self._fallback.summarise(repo, last_known_tag, new_tags)
        if not usable_summary(text):
            log.warning("summary model gave an unusable answer, using the template")
            return self._fallback.summarise(repo, last_known_tag, new_tags)
        return text

    def _ask(self, repo: str, last_known_tag: str, new_tags: Sequence[str]) -> str:
        prompt = summary_prompt(repo, last_known_tag, new_tags)
        return self._factory(self._model_name).invoke(prompt).text.strip()
