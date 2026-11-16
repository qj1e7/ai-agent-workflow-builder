"""The Langfuse adapter of the tracing port (ADR 0050). Only the API's start-up code builds it."""

import logging
import time
from collections.abc import Callable, Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

import httpx
from langchain_core.language_models import BaseChatModel
from langfuse import Langfuse, propagate_attributes
from langfuse.langchain import CallbackHandler
from langfuse.types import (
    AttributeValue,
    MaskOtelSpansParams,
    MaskOtelSpansResult,
    OtelSpanIdentifier,
    OtelSpanPatch,
)
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SpanExporter

from agent_runtime.contract import AnswerRequest, AnswerResult, TaskRequest
from agent_runtime.monitoring.masking import Masker
from agent_runtime.monitoring.tracing import (
    NoTracing,
    Traced,
    TracedTurn,
    TurnOutcome,
    answer_kind,
    code_flags,
    fell_back_notes,
)
from agent_runtime.summary import ChatFor

log = logging.getLogger(__name__)

TURN_NAME = "planner-turn"
RUN_NAME = "agent-run"
# How spans leave, set here rather than left to the SDK's environment, because the masker's grace
# must outlast the longest a span can wait to be masked: one flush interval, then a full queue of
# batches (OpenTelemetry's 2048 spans) each taking up to the timeout.
FLUSH_AT: Final = 512
FLUSH_INTERVAL_SECONDS: Final = 5.0
TIMEOUT_SECONDS: Final = 5
QUEUE_SIZE: Final = 2048
LONGEST_EXPORT_WAIT: Final = FLUSH_INTERVAL_SECONDS + QUEUE_SIZE / FLUSH_AT * TIMEOUT_SECONDS


@dataclass(frozen=True)
class LangfuseSettings:
    public_key: str
    secret_key: str
    base_url: str
    environment: str | None = None
    release: str | None = None


class _MaskedError(Exception):
    """An error's words with every secret masked. Langfuse writes an error's words into the
    span's status, which `mask_otel_spans` cannot change."""


class _Callbacks(CallbackHandler):
    def __init__(self, masker: Masker, public_key: str) -> None:
        super().__init__(public_key=public_key)
        self._masker = masker

    def _masked(self, error: BaseException) -> _MaskedError:
        return _MaskedError(self._masker.mask(f"{type(error).__name__}: {error}"))

    def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> Any:
        return super().on_llm_error(self._masked(error), run_id=run_id, **kwargs)

    def on_chain_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> Any:
        return super().on_chain_error(self._masked(error), run_id=run_id, **kwargs)

    def on_tool_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> Any:
        return super().on_tool_error(self._masked(error), run_id=run_id, **kwargs)

    def on_retriever_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> Any:
        return super().on_retriever_error(self._masked(error), run_id=run_id, **kwargs)


class _Trace:
    def __init__(self, callbacks: _Callbacks) -> None:
        self._callbacks = callbacks

    def models(self, chat_for: ChatFor) -> ChatFor:
        def traced(timeout: float) -> BaseChatModel:
            model = chat_for(timeout)
            return model.model_copy(update={"callbacks": [self._callbacks]})

        return traced


class _Turn(_Trace):
    def __init__(self, callbacks: _Callbacks, finish: Callable[[AnswerResult], None]) -> None:
        super().__init__(callbacks)
        self._finish = finish

    def answered(self, result: AnswerResult) -> None:
        self._finish(result)


class LangfuseTracing:
    def __init__(
        self,
        settings: LangfuseSettings,
        masker: Masker,
        span_exporter: SpanExporter | None = None,
        httpx_client: httpx.Client | None = None,
    ) -> None:
        self._masker = masker
        self._public_key = settings.public_key
        # A provider of its own, so no other OpenTelemetry instrumentation sends spans here.
        self._client = Langfuse(
            public_key=settings.public_key,
            secret_key=settings.secret_key,
            base_url=settings.base_url,
            environment=settings.environment,
            release=settings.release,
            mask_otel_spans=self._mask_spans,
            flush_at=FLUSH_AT,
            flush_interval=FLUSH_INTERVAL_SECONDS,
            timeout=TIMEOUT_SECONDS,
            tracer_provider=TracerProvider(),
            span_exporter=span_exporter,
            httpx_client=httpx_client,
        )

    @contextmanager
    def turn(self, request: AnswerRequest) -> Generator[TracedTurn]:
        with self._holding(request.model.api_key) as traced:
            if not traced:
                with NoTracing().turn(request) as untraced:
                    yield untraced
                return
            with self._turn(request) as turn:
                yield turn

    @contextmanager
    def run(self, request: TaskRequest) -> Generator[Traced]:
        secrets = (request.callback.token, request.model.api_key if request.model else None)
        with self._holding(*secrets) as traced:
            if not traced:
                with NoTracing().run(request) as untraced:
                    yield untraced
                return
            with self._run(request) as run:
                yield run

    @contextmanager
    def _holding(self, *secrets: str | None) -> Generator[bool]:
        """Holds the secrets handed over with a call until its trace has ended. When the masker
        holds as many as it can, the trace is not sent at all."""
        held = self._masker.hold(*secrets)
        if held is None:
            log.warning("Not traced: the masker already holds %d secrets", self._masker.holding)
            yield False
            return
        try:
            yield True
        finally:
            self._masker.release(held)

    @contextmanager
    def _turn(self, request: AnswerRequest) -> Generator[TracedTurn]:
        trace = request.trace
        started = time.monotonic()
        raised: BaseException | None = None
        with (
            self._client.start_as_current_observation(
                name=TURN_NAME,
                as_type="span",
                input=request.task,
                trace_context={"trace_id": trace.id} if trace else None,
            ) as span,
            propagate_attributes(
                trace_name=TURN_NAME,
                user_id=trace.person if trace else None,
                session_id=trace.chat if trace else None,
                metadata={"model": request.model.model},
            ),
            fell_back_notes() as notes,
        ):

            def finish(result: AnswerResult) -> None:
                outcome = TurnOutcome(result, time.monotonic() - started, next(iter(notes), None))
                flags = code_flags(outcome)
                kind = answer_kind(result)
                metadata = {"answer_kind": kind}
                if outcome.fell_back is not None:
                    metadata["fell_back"] = outcome.fell_back
                if flags:
                    metadata["flagged"] = "true"
                span.update(output=result.model_dump(mode="json"))
                # The SDK sets trace attributes only this way, on the current span, the turn's.
                with propagate_attributes(tags=[kind], metadata=metadata):
                    pass
                for flag in flags:
                    self._client.create_score(
                        name=flag,
                        value=1,
                        data_type="BOOLEAN",
                        trace_id=span.trace_id,
                        score_id=f"{span.trace_id}-{flag}",
                    )

            try:
                yield _Turn(self._callbacks(), finish)
            except BaseException as error:
                raised = error
                span.update(level="ERROR", status_message=type(error).__name__)
        if raised is not None:
            # Raised outside the span, so OpenTelemetry never writes the error's words into it.
            raise raised

    @contextmanager
    def _run(self, request: TaskRequest) -> Generator[Traced]:
        raised: BaseException | None = None
        with (
            self._client.start_as_current_observation(
                name=RUN_NAME, as_type="span", input=request.instruction
            ) as span,
            propagate_attributes(trace_name=RUN_NAME, session_id=request.run_id),
        ):
            try:
                yield _Trace(self._callbacks())
            except BaseException as error:
                raised = error
                span.update(level="ERROR", status_message=type(error).__name__)
        if raised is not None:
            raise raised

    def flush(self) -> None:
        self._client.flush()

    def shutdown(self) -> None:
        self._client.shutdown()

    def _callbacks(self) -> _Callbacks:
        return _Callbacks(self._masker, self._public_key)

    def _mask_spans(self, *, params: MaskOtelSpansParams) -> MaskOtelSpansResult:
        patches: dict[OtelSpanIdentifier, OtelSpanPatch | None] = {}
        for identifier, span in params.spans.items():
            changed = {
                key: masked
                for key, value in span.attributes.items()
                if (masked := self._masked(value)) != value
            }
            if changed:
                patches[identifier] = OtelSpanPatch(set_attributes=changed)
        return MaskOtelSpansResult(span_patches=patches)

    def _masked(self, value: AttributeValue) -> AttributeValue:
        if isinstance(value, str):
            return self._masker.mask(value)
        if isinstance(value, Sequence) and all(isinstance(item, str) for item in value):
            masked = tuple(self._masker.mask(item) for item in value if isinstance(item, str))
            return masked if masked != tuple(value) else value
        return value
