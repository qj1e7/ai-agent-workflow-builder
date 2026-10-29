import re
import time
from collections.abc import Callable

import httpx
from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, ValidationError

from agent_runtime.addresses import AddressPolicy, AddressRefused, AddressRefusedError
from agent_runtime.contract import (
    Connected,
    ConnectRequest,
    ConnectResult,
    Finding,
    FoundModel,
    ModelAccess,
    ModelProblem,
    ModelStyle,
    ModelTestPassed,
    ModelTestResult,
)
from agent_runtime.guarded import GuardedModels, GuardedTransport
from agent_runtime.summary import (
    SUMMARY_TIMEOUT_SECONDS,
    ChatFor,
    Checked,
    ModelFactory,
    ModelSummarizer,
    Summarizer,
    check_prompt,
    usable_summary,
)

ANTHROPIC_VERSION = "2023-06-01"
LIST_TIMEOUT_SECONDS = 10.0
SAMPLE_CHECK = [
    Checked(
        "LangGraph",
        Finding(
            software_id="sw_sample",
            state="behind",
            newest="1.2.16",
            new_versions=["1.2.16", "1.2.15"],
            detail="2 releases newer than 1.2.14.",
        ),
    )
]
# A name with one of these words marks a model that cannot write text.
NOT_TEXT = re.compile(
    r"embed|whisper|tts|dall-e|moderation|rerank|transcribe|speech|image|audio", re.IGNORECASE
)
# A name with one of these words usually marks a model fast enough for a summary.
FAST = re.compile(r"haiku|mini|flash|small|lite|nano", re.IGNORECASE)

KEY_REFUSED = "The address answered, but it refused this key. Check that you copied all of it."
UNREACHABLE = "Nobody answered at that address. Check it and try again."

type FactoryFor = Callable[[ModelAccess], ModelFactory]


class _ListedModel(BaseModel):
    id: str
    type: str | None = None
    display_name: str | None = None


class _ModelList(BaseModel):
    data: list[_ListedModel]


def summarizer_for(access: ModelAccess, policy: AddressPolicy, models: GuardedModels) -> Summarizer:
    # The address is checked before each task as well as at every connection, because a setting
    # saved last week can now name an address the deployment no longer allows.
    def build(name: str) -> BaseChatModel:
        refused = policy.check(access.base_url)
        if refused is not None:
            raise AddressRefusedError(refused)
        return models.factory_for(access)(name)

    return ModelSummarizer(access.model, factory=build)


def chat_for(access: ModelAccess, policy: AddressPolicy, models: GuardedModels) -> ChatFor:
    """The chat model for an agent card's run, draft or choice. It checks the address each time
    a model is built, like the summarizer does."""

    def build(timeout: float) -> BaseChatModel:
        refused = policy.check(access.base_url)
        if refused is not None:
            raise AddressRefusedError(refused)
        return models.factory_for(access, timeout)(access.model)

    return build


class ModelProbe:
    def __init__(
        self,
        policy: AddressPolicy,
        client: httpx.Client | None = None,
        factory_for: FactoryFor | None = None,
        clock: Callable[[], float] = time.monotonic,
        models: GuardedModels | None = None,
    ) -> None:
        self._policy = policy
        self._client = client or httpx.Client(
            transport=GuardedTransport(policy),
            timeout=LIST_TIMEOUT_SECONDS,
            follow_redirects=False,
        )
        self._factory_for = factory_for or (models or GuardedModels(policy)).factory_for
        self._clock = clock

    def connect(self, request: ConnectRequest) -> ConnectResult:
        refused = self._policy.check(request.base_url)
        if refused is not None:
            return ModelProblem(reason=refused.reason, message=refused.message)
        # Both header styles, because the answer is what tells us which style the address speaks.
        headers = {
            "x-api-key": request.api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "Authorization": f"Bearer {request.api_key}",
        }
        for prefix in _list_prefixes(request.base_url.rstrip("/")):
            try:
                response = self._client.get(f"{prefix}/models", headers=headers)
            except AddressRefusedError as error:
                return ModelProblem(reason=error.refused.reason, message=error.refused.message)
            except httpx.HTTPError:
                return ModelProblem(reason="unreachable", message=UNREACHABLE)
            if response.status_code in (401, 403):
                return ModelProblem(reason="key_refused", message=KEY_REFUSED)
            if response.is_redirect:
                return ModelProblem(
                    reason="address_not_allowed",
                    message="The address sent us somewhere else, and the platform does not "
                    "follow that. Use the final address instead.",
                )
            if response.status_code == 200:
                found = _connected(response.content, prefix)
                if found is not None:
                    return found
        return ModelProblem(
            reason="not_a_model_api",
            message="The address answered, but not like an OpenAI-style or Anthropic-style model "
            "API. Check the address.",
        )

    def test(self, access: ModelAccess) -> ModelTestResult:
        refused = self._policy.check(access.base_url)
        if refused is not None:
            return ModelProblem(reason=refused.reason, message=refused.message)
        prompt = check_prompt(SAMPLE_CHECK)
        started = self._clock()
        try:
            text = self._factory_for(access)(access.model).invoke(prompt).text.strip()
        except Exception as error:
            return problem_for(error)
        seconds = round(self._clock() - started, 1)
        if seconds > SUMMARY_TIMEOUT_SECONDS:
            return ModelProblem(
                reason="too_slow",
                message=f"The model answered in {seconds} seconds. Summaries wait "
                f"{SUMMARY_TIMEOUT_SECONDS} seconds, so runs would use the built-in sentence. "
                "Pick a faster model.",
            )
        if not usable_summary(text):
            return ModelProblem(
                reason="unusable_answer",
                message="The model answered, but not with one short sentence, so runs would use "
                "the built-in sentence. Pick another model.",
            )
        return ModelTestPassed(seconds=seconds, text=text)


def _list_prefixes(base: str) -> tuple[str, ...]:
    # Most providers list models under /v1. Some, like Gemini's OpenAI endpoint, under the address.
    return (base,) if base.endswith("/v1") else (f"{base}/v1", base)


def _connected(content: bytes, prefix: str) -> ConnectResult | None:
    try:
        listed = _ModelList.model_validate_json(content).data
    except ValidationError:
        return None
    if not listed:
        return None
    anthropic = all(m.type == "model" for m in listed)
    models = [
        FoundModel(id=m.id, display=m.display_name or m.id, suggested=bool(FAST.search(m.id)))
        for m in listed
        if not NOT_TEXT.search(m.id)
    ]
    if not models:
        return ModelProblem(
            reason="no_text_models", message="The key works, but none of its models can write text."
        )
    style: ModelStyle = "anthropic" if anthropic else "openai"
    # Anthropic's client adds /v1/messages to the address, and OpenAI's adds /chat/completions.
    base_url = prefix.removesuffix("/v1") if anthropic else prefix
    return Connected(style=style, base_url=base_url, models=models)


def _refusal_behind(error: BaseException) -> AddressRefused | None:
    # The clients wrap whatever the transport raises, so look through the chain of causes.
    seen: BaseException | None = error
    for _ in range(10):
        if seen is None:
            return None
        if isinstance(seen, AddressRefusedError):
            return seen.refused
        seen = seen.__cause__ or seen.__context__
    return None


def problem_for(error: Exception, runs_fall_back: bool = True) -> ModelProblem:
    """The plain reason a model call failed. A card's draft or choice has no built-in sentence to
    fall back on, so it passes runs_fall_back=False."""
    refused = _refusal_behind(error)
    if refused is not None:
        return ModelProblem(reason=refused.reason, message=refused.message)
    # Only the status and the error's type are used. The provider's words can quote the key.
    status: object = getattr(error, "status_code", None)
    name = type(error).__name__
    if status in (401, 403):
        return ModelProblem(reason="key_refused", message=KEY_REFUSED)
    if status == 404:
        return ModelProblem(
            reason="model_not_found",
            message="The address does not offer this model. Connect again and pick one from the "
            "list.",
        )
    if "Timeout" in name and not runs_fall_back:
        return ModelProblem(
            reason="too_slow",
            message="The model did not answer in time. Try again, or pick a faster model.",
        )
    if "Timeout" in name:
        return ModelProblem(
            reason="too_slow",
            message=f"The model did not answer within {SUMMARY_TIMEOUT_SECONDS} seconds, so runs "
            "would use the built-in sentence. Pick a faster model.",
        )
    if "Connection" in name:
        return ModelProblem(reason="unreachable", message=UNREACHABLE)
    detail = f"the provider answered {status}" if isinstance(status, int) else name
    return ModelProblem(reason="failed", message=f"The model call failed ({detail}).")
