from collections.abc import Callable, Iterator

import pytest
from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from agent_runtime.contract import Finding
from agent_runtime.summary import Checked, ModelSummarizer, TemplateSummarizer, model_factory

TEMPLATE = "1 of 1 watched software has new releases: LangGraph 1.2.16."
BEHIND = [
    Checked(
        "LangGraph",
        Finding(
            software_id="sw_01LANGGRAPH",
            state="behind",
            newest="1.2.16",
            new_versions=["1.2.16", "1.2.15"],
            detail="2 releases newer than 1.2.14.",
        ),
    )
]


def answering(*replies: str) -> Callable[[str], BaseChatModel]:
    def factory(name: str) -> BaseChatModel:
        messages: Iterator[AIMessage] = iter(AIMessage(content=r) for r in replies)
        return GenericFakeChatModel(messages=messages)

    return factory


def broken(name: str) -> BaseChatModel:
    raise RuntimeError("the provider is down")


def test_template_is_plain_and_counts_correctly():
    assert TemplateSummarizer().summarise_check(BEHIND) == TEMPLATE


def test_model_text_is_used_when_the_model_answers():
    sentence = "Two new LangGraph versions came out, 1.2.16 and 1.2.15."
    summarizer = ModelSummarizer("any:model", factory=answering(f"  {sentence}\n"))
    assert summarizer.summarise_check(BEHIND) == sentence


def test_model_failure_falls_back_to_the_template():
    assert ModelSummarizer("any:model", factory=broken).summarise_check(BEHIND) == TEMPLATE


def test_a_model_name_no_provider_knows_falls_back_to_the_template():
    assert ModelSummarizer("no-such-model").summarise_check(BEHIND) == TEMPLATE


def test_a_provider_package_that_is_not_installed_falls_back_to_the_template():
    assert ModelSummarizer("openai:gpt-4o").summarise_check(BEHIND) == TEMPLATE


@pytest.mark.parametrize("reply", ["", "   ", "line one\nline two", "x" * 301])
def test_an_unusable_answer_falls_back_to_the_template(reply: str):
    summarizer = ModelSummarizer("any:model", factory=answering(reply))
    assert summarizer.summarise_check(BEHIND) == TEMPLATE


def test_a_gateway_model_gets_the_gateway_address_and_key():
    model = model_factory("https://gateway.example", "sk-test")("anthropic:claude-test")
    assert isinstance(model, ChatAnthropic)
    assert model.anthropic_api_url == "https://gateway.example"
    assert model.anthropic_api_key.get_secret_value() == "sk-test"


def test_a_gateway_model_keeps_the_ten_second_single_try():
    model = model_factory("https://gateway.example", "sk-test")("anthropic:claude-test")
    assert isinstance(model, ChatAnthropic)
    assert model.default_request_timeout == 10
    assert model.max_retries == 0
