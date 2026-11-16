"""The Langfuse adapter of the tracing port (ADR 0050). Only the API's start-up code builds it."""

import logging
import threading
import time
from collections.abc import Callable, Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Final, cast
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
from agent_runtime.monitoring.masking import Held, Masker
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

# The most traces open, or ended and waiting for their top span to be exported, at once. Past it a
# new trace is not sent at all, and no open trace is forgotten to make room.
TRACES_LIMIT: Final = 1024
# An ended trace whose top span has not been exported in this long may be forgotten to make room.
# That is safe: a span of a forgotten trace is dropped at export, never sent unmasked.
FORGET_AFTER_SECONDS: Final = 600.0
# Langfuse drops a span whose patch is not an OtelSpanPatch (MaskOtelSpansResult's docs).
# test_trace_masking.py checks that it still does.
DROP: Final = cast(OtelSpanPatch, "drop")


@dataclass(frozen=True)
class LangfuseSettings:
    public_key: str
    secret_key: str
    base_url: str
    environment: str | None = None
    release: str | None = None


class _MaskedError(Exception):
    """Langfuse writes an error's words into the span's status, which `mask_otel_spans` cannot
    change."""


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


@dataclass
class _Open:
    """One trace this adapter sends: the secrets its calls were handed, the id of its top span
    once it started, and when it ended."""

    held: Held
    top: str | None = None
    ended_at: float | None = None


class LangfuseTracing:
    """Masks in two places. Each span's input, output and metadata are masked as they are set,
    while the trace's secrets are held. At export every attribute is masked again, and a span of
    a trace this adapter no longer tracks is dropped, so nothing leaves unmasked whenever the
    exporter runs. A trace is tracked from before its top span starts until that span has been
    exported."""

    def __init__(
        self,
        settings: LangfuseSettings,
        masker: Masker,
        span_exporter: SpanExporter | None = None,
        httpx_client: httpx.Client | None = None,
        limit: int = TRACES_LIMIT,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._masker = masker
        self._public_key = settings.public_key
        self._limit = limit
        self._clock = clock
        self._open: dict[str, _Open] = {}
        self._lock = threading.Lock()
        # A provider of its own, so no other OpenTelemetry instrumentation sends spans here.
        self._client = Langfuse(
            public_key=settings.public_key,
            secret_key=settings.secret_key,
            base_url=settings.base_url,
            environment=settings.environment,
            release=settings.release,
            mask=self._mask_data,
            mask_otel_spans=self._mask_spans,
            tracer_provider=TracerProvider(),
            span_exporter=span_exporter,
            httpx_client=httpx_client,
        )

    @property
    def tracked(self) -> int:
        """How many traces are open, or ended and waiting for their top span to be exported."""
        with self._lock:
            return len(self._open)

    @contextmanager
    def turn(self, request: AnswerRequest) -> Generator[TracedTurn]:
        trace_id = request.trace.id if request.trace else Langfuse.create_trace_id()
        with self._tracking(trace_id, request.model.api_key) as tracked:
            if not tracked:
                with NoTracing().turn(request) as untraced:
                    yield untraced
                return
            with self._turn(request, trace_id) as turn:
                yield turn

    @contextmanager
    def run(self, request: TaskRequest) -> Generator[Traced]:
        trace_id = Langfuse.create_trace_id()
        secrets = (request.callback.token, request.model.api_key if request.model else None)
        with self._tracking(trace_id, *secrets) as tracked:
            if not tracked:
                with NoTracing().run(request) as untraced:
                    yield untraced
                return
            with self._run(request, trace_id) as run:
                yield run

    def flush(self) -> None:
        self._client.flush()

    def shutdown(self) -> None:
        self._client.shutdown()

    @contextmanager
    def _tracking(self, trace_id: str, *secrets: str | None) -> Generator[bool]:
        if not self._track(trace_id, secrets):
            log.warning("Not traced: %d traces are already tracked", self.tracked)
            yield False
            return
        try:
            yield True
        finally:
            self._ended(trace_id)

    def _track(self, trace_id: str, secrets: Sequence[str | None]) -> bool:
        with self._lock:
            if trace_id in self._open:
                return False
            if len(self._open) >= self._limit:
                self._forget_long_ended()
            if len(self._open) >= self._limit:
                return False
            self._open[trace_id] = _Open(self._masker.hold(*secrets))
            return True

    def _started(self, trace_id: str, top: str) -> None:
        with self._lock:
            self._open[trace_id].top = top

    def _ended(self, trace_id: str) -> None:
        with self._lock:
            trace = self._open.get(trace_id)
            if trace is None:
                # Its top span ended and was exported already.
                return
            if trace.top is None:
                # Its top span never started, so no span of it waits to be exported.
                self._forget(trace_id)
            else:
                trace.ended_at = self._clock()

    def _forget_long_ended(self) -> None:
        now = self._clock()
        for trace_id, trace in list(self._open.items()):
            if trace.ended_at is not None and now - trace.ended_at >= FORGET_AFTER_SECONDS:
                self._forget(trace_id)

    def _forget(self, trace_id: str) -> None:
        self._masker.release(self._open.pop(trace_id).held)

    @contextmanager
    def _turn(self, request: AnswerRequest, trace_id: str) -> Generator[TracedTurn]:
        trace = request.trace
        started = time.monotonic()
        raised: BaseException | None = None
        with (
            self._client.start_as_current_observation(
                name=TURN_NAME,
                as_type="span",
                input=request.task,
                trace_context={"trace_id": trace_id},
            ) as span,
            propagate_attributes(
                trace_name=TURN_NAME,
                user_id=trace.person if trace else None,
                session_id=trace.chat if trace else None,
                metadata={"model": request.model.model},
            ),
            fell_back_notes() as notes,
        ):
            self._started(trace_id, span.id)

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
    def _run(self, request: TaskRequest, trace_id: str) -> Generator[Traced]:
        raised: BaseException | None = None
        with (
            self._client.start_as_current_observation(
                name=RUN_NAME,
                as_type="span",
                input=request.instruction,
                trace_context={"trace_id": trace_id},
            ) as span,
            propagate_attributes(trace_name=RUN_NAME, session_id=request.run_id),
        ):
            self._started(trace_id, span.id)
            try:
                yield _Trace(self._callbacks())
            except BaseException as error:
                raised = error
                span.update(level="ERROR", status_message=type(error).__name__)
        if raised is not None:
            raise raised

    def _callbacks(self) -> _Callbacks:
        return _Callbacks(self._masker, self._public_key)

    def _mask_data(self, *, data: Any, **_: Any) -> Any:
        return self._masker.mask_data(data)

    def _mask_spans(self, *, params: MaskOtelSpansParams) -> MaskOtelSpansResult:
        # Under the lock, so no trace is forgotten while its spans are being masked.
        with self._lock:
            patches: dict[OtelSpanIdentifier, OtelSpanPatch | None] = {}
            exported: list[str] = []
            for identifier, span in params.spans.items():
                trace = self._open.get(span.trace_id)
                if trace is None:
                    patches[identifier] = DROP
                    continue
                if span.span_id == trace.top:
                    exported.append(span.trace_id)
                changed = {
                    key: masked
                    for key, value in span.attributes.items()
                    if (masked := self._masked_attribute(value)) != value
                }
                if changed:
                    patches[identifier] = OtelSpanPatch(set_attributes=changed)
            # A top span ends after every other span of its trace, so all of them are masked now.
            for trace_id in exported:
                self._forget(trace_id)
            return MaskOtelSpansResult(span_patches=patches)

    def _masked_attribute(self, value: AttributeValue) -> AttributeValue:
        if isinstance(value, str):
            return self._masker.mask(value)
        if isinstance(value, Sequence) and all(isinstance(item, str) for item in value):
            masked = tuple(self._masker.mask(item) for item in value if isinstance(item, str))
            return masked if masked != tuple(value) else value
        return value
