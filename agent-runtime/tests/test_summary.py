from collections.abc import Callable, Iterator

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from agent_runtime.summary import ModelSummarizer, TemplateSummarizer

TEMPLATE = "2 new releases: 1.2.16, 1.2.15"
NEW = ["1.2.16", "1.2.15"]


def answering(*replies: str) -> Callable[[str], BaseChatModel]:
    def factory(name: str) -> BaseChatModel:
        messages: Iterator[AIMessage] = iter(AIMessage(content=r) for r in replies)
        return GenericFakeChatModel(messages=messages)

    return factory


def broken(name: str) -> BaseChatModel:
    raise RuntimeError("the provider is down")


def test_template_is_plain_and_counts_correctly():
    template = TemplateSummarizer()
    assert template.summarise("o/r", "1.2.14", NEW) == TEMPLATE
    assert template.summarise("o/r", "1.2.14", ["1.2.15"]) == "1 new release: 1.2.15"


def test_model_text_is_used_when_the_model_answers():
    sentence = "Two new LangGraph versions came out, 1.2.16 and 1.2.15."
    summarizer = ModelSummarizer("any:model", factory=answering(f"  {sentence}\n"))
    assert summarizer.summarise("o/r", "1.2.14", NEW) == sentence


def test_model_failure_falls_back_to_the_template():
    assert ModelSummarizer("any:model", factory=broken).summarise("o/r", "1.2.14", NEW) == TEMPLATE


def test_a_model_name_no_provider_knows_falls_back_to_the_template():
    assert ModelSummarizer("no-such-model").summarise("o/r", "1.2.14", NEW) == TEMPLATE


def test_a_provider_package_that_is_not_installed_falls_back_to_the_template():
    assert ModelSummarizer("openai:gpt-4o").summarise("o/r", "1.2.14", NEW) == TEMPLATE


@pytest.mark.parametrize("reply", ["", "   ", "line one\nline two", "x" * 301])
def test_an_unusable_answer_falls_back_to_the_template(reply: str):
    summarizer = ModelSummarizer("any:model", factory=answering(reply))
    assert summarizer.summarise("o/r", "1.2.14", NEW) == TEMPLATE
