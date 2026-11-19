"""The exits and inputs of n8n's blocks (ADR 0051, section 8, as amended): where a wire may leave
one block and join another, read from the catalogue of the pinned n8n image. Plain code, with no
model.

n8n gives most blocks a list of outputs and inputs. Each is of a kind, `main` or an AI kind such
as `ai_languageModel`, and may have a name (`outputNames`, `inputNames`, or its `displayName`). A
few blocks compute theirs from their parameters, and the catalogue keeps n8n's expression for
them word for word. `RULES` resolves each such expression the way n8n does. `BY_HAND` holds the
expressions of AI blocks whose AI inputs depend on their parameters: code gives each the main
input n8n always gives it, and lets any AI wire join it. Both are keyed by the digest of the
expression's text, so a new pin that changes one fails a test until someone reads it again. An
expression in neither has no exits and no inputs, so no wire passes.
"""

import hashlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, cast

type Json = dict[str, Any]
type Values = Mapping[str, object]

MAIN: Final = "main"
MOST: Final = 80
"""The most exits or inputs code makes for a block whose parameters set how many by a number, as
many as a plan's wires. A model writes the number, so it is held to what a plan could use. A list,
such as a Switch's rules, gives as many as n8n makes, and a block's parameters are held to
20,000 characters."""


@dataclass(frozen=True)
class Link:
    """One of a block's exits or inputs."""

    kind: str
    """n8n's kind of connection: main, or an AI kind such as ai_languageModel."""
    name: str | None = None
    """What n8n calls it, if anything."""


@dataclass(frozen=True)
class Inputs:
    links: tuple[Link, ...]
    any_ai: bool = False
    """Whether code keeps the block's inputs by hand, so a wire of any AI kind may join it."""


@dataclass(frozen=True)
class Rule:
    blocks: str
    """The blocks and versions n8n computes these with."""
    says: str
    """How the parameters set them, for the drafter."""
    resolve: Callable[[Values, float], Sequence[Link]]


@dataclass(frozen=True)
class Hand:
    blocks: str
    main: int
    """How many main inputs n8n gives the block, whatever its parameters."""


def digest(expression: str) -> str:
    """How `RULES` and `BY_HAND` name one of n8n's expressions."""
    return hashlib.sha256(expression.encode()).hexdigest()[:16]


def exits(group: Json, version: float, values: Values) -> tuple[Link, ...]:
    """The exits of one version of a block, in n8n's order of its outputs, for these parameter
    values with n8n's defaults. One with no name among several of its kind is named by its
    number from 0, so that a wire can name it."""
    served = group.get("outputs")
    if isinstance(served, str):
        rule = RULES.get(digest(served))
        found = () if rule is None else tuple(rule.resolve(values, version))
    else:
        found = _listed(served, group.get("outputNames"))
    return _addressable(found)


def _addressable(found: Sequence[Link]) -> tuple[Link, ...]:
    kinds = [link.kind for link in found]
    return tuple(
        link if link.name is not None or kinds.count(link.kind) == 1 else Link(link.kind, str(at))
        for at, link in enumerate(found)
    )


def inputs(group: Json, version: float, values: Values) -> Inputs:
    """The inputs of one version of a block, in n8n's order, for these parameter values with
    n8n's defaults."""
    served = group.get("inputs")
    if not isinstance(served, str):
        return Inputs(_listed(served, group.get("inputNames")))
    key = digest(served)
    if (rule := RULES.get(key)) is not None:
        return Inputs(tuple(rule.resolve(values, version)))
    if (hand := BY_HAND.get(key)) is not None:
        return Inputs((Link(MAIN),) * hand.main, any_ai=True)
    return Inputs(())


def described(group: Json) -> Json:
    """The exits and inputs as describe_block gives them: the name a wire gives each exit, and
    each input's kind and its number among the inputs of that kind, which is what a wire's input
    counts. For a block whose parameters set them, the words say how."""
    return {"exits": _exits_said(group), "inputs": _inputs_said(group)}


def _exits_said(group: Json) -> str | list[str]:
    served = group.get("outputs")
    if isinstance(served, str):
        return _computed(served)
    links = _addressable(_listed(served, group.get("outputNames")))
    if len(links) == 1:
        return [links[0].kind]
    return [link.name or link.kind for link in links]


def _inputs_said(group: Json) -> str | list[Json]:
    served = group.get("inputs")
    if isinstance(served, str):
        return _computed(served)
    said: list[Json] = []
    counted: dict[str, int] = {}
    for link in _listed(served, group.get("inputNames")):
        number = counted.get(link.kind, 0)
        counted[link.kind] = number + 1
        said.append(
            {"kind": link.kind, "input": number} | ({"name": link.name} if link.name else {})
        )
    return said


def _computed(served: str) -> str:
    key = digest(served)
    if (rule := RULES.get(key)) is not None:
        return rule.says
    if (hand := BY_HAND.get(key)) is not None:
        main = "One main input, input 0" if hand.main else "No main input"
        return f"{main}, and any wire from a block made for an AI agent, at input 0."
    return "Code can't tell on this n8n, so no wire passes."


def _listed(served: object, names: object) -> tuple[Link, ...]:
    listed = cast(list[object], served) if isinstance(served, list) else []
    named = cast(list[object], names) if isinstance(names, list) else []
    links: list[Link] = []
    for at, link in enumerate(listed):
        entry = cast(Json, link) if isinstance(link, dict) else {"type": link}
        name = named[at] if at < len(named) else entry.get("displayName")
        links.append(Link(str(entry.get("type")), _name(name)))
    return tuple(links)


def _name(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _mapping(value: object) -> Values:
    return cast(Values, value) if isinstance(value, dict) else {}


def _items(value: object) -> list[Values]:
    listed = cast(list[object], value) if isinstance(value, list) else []
    return [_mapping(item) for item in listed]


def _text(value: object) -> str | None:
    """A name written out. One an expression gives is unknown until the run."""
    return value if isinstance(value, str) and value and not value.startswith("=") else None


def _count(value: object, otherwise: int) -> int:
    """How many, as JavaScript reads `value || otherwise` for a length, held to `MOST`."""
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        return otherwise
    return min(int(value), MOST)


def _numbered(count: int) -> tuple[Link, ...]:
    return tuple(Link(MAIN, str(at)) for at in range(count))


# The rules, each as n8n's expression for it reads.


def _switch(values: Values, version: float) -> Sequence[Link]:
    if values.get("mode") == "expression":
        return _numbered(_count(values.get("numberOutputs"), 0))
    rules = _items(_mapping(values.get("rules")).get("values"))
    links = [Link(MAIN, _text(rule.get("outputKey")) or str(at)) for at, rule in enumerate(rules)]
    options = _mapping(values.get("options"))
    if options.get("fallbackOutput") == "extra":
        links.append(Link(MAIN, _text(options.get("renameFallbackOutput")) or "Fallback"))
    return links


def _switch_2(values: Values, version: float) -> Sequence[Link]:
    if values.get("mode") == "expression":
        return _numbered(_count(values.get("outputsAmount"), 0))
    rules = _items(_mapping(values.get("rules")).get("rules"))
    return [Link(MAIN, _text(rule.get("outputKey"))) for rule in rules]


def _merge(values: Values, version: float) -> Sequence[Link]:
    count = _count(values.get("numberInputs"), 2)
    return [Link(MAIN, f"Input {at + 1}") for at in range(count)]


def _webhook(values: Values, version: float) -> Sequence[Link]:
    method = values.get("httpMethod")
    if isinstance(method, list):
        return [Link(MAIN, _text(m)) for m in cast(list[object], method)]
    return [Link(MAIN, _text(method))]


def _respond(values: Values, version: float) -> Sequence[Link]:
    if version == 1.3 or (version >= 1.4 and bool(values.get("enableResponseOutput"))):
        return [Link(MAIN, "Input Data"), Link(MAIN, "Response")]
    return [Link(MAIN)]


def _classes(values: Values, version: float) -> Sequence[Link]:
    categories = _items(_mapping(values.get("categories")).get("categories"))
    links = [Link(MAIN, _text(category.get("category"))) for category in categories]
    if _mapping(values.get("options")).get("fallback") == "other":
        links.append(Link(MAIN, "Other"))
    return links


def _sentiment(values: Values, version: float) -> Sequence[Link]:
    said = _mapping(values.get("options")).get("categories")
    categories = said if isinstance(said, str) else "Positive, Neutral, Negative"
    return [Link(MAIN, _name(c.strip())) for c in categories.split(",")]


def _guardrails(values: Values, version: float) -> Sequence[Link]:
    operation = values.get("operation")
    if operation is None or operation == "classify":
        return [Link(MAIN, "Pass"), Link(MAIN, "Fail")]
    return [Link(MAIN)]


CHAT_MODEL: Final = Link("ai_languageModel", "Chat Model")
LLM_CHECKS: Final = frozenset({"nsfw", "topicalAlignment", "custom", "jailbreak"})


def _guardrails_takes(values: Values, version: float) -> Sequence[Link]:
    if any(check in LLM_CHECKS for check in _mapping(values.get("guardrails"))):
        return [Link(MAIN), CHAT_MODEL]
    return [Link(MAIN)]


def _guardrails_1_takes(values: Values, version: float) -> Sequence[Link]:
    return [Link(MAIN)] if values.get("operation") == "sanitize" else [Link(MAIN), CHAT_MODEL]


def _evaluation(values: Values, version: float) -> Sequence[Link]:
    if values.get("operation") == "checkIfEvaluating":
        return [Link(MAIN, "Evaluation"), Link(MAIN, "Normal")]
    return [Link(MAIN)]


def _evaluation_takes(values: Values, version: float) -> Sequence[Link]:
    graded = values.get("metric") in ("correctness", "helpfulness")
    if values.get("operation") == "setMetrics" and graded:
        return [Link(MAIN), Link("ai_languageModel", "Model")]
    return [Link(MAIN)]


def _vector_store(values: Values, version: float) -> Sequence[Link]:
    mode = values.get("mode")
    if mode == "retrieve-as-tool":
        return [Link("ai_tool", "Tool")]
    if mode is None or mode == "retrieve":
        return [Link("ai_vectorStore", "Vector Store")]
    return [Link(MAIN)]


def _vector_store_takes(values: Values, version: float) -> Sequence[Link]:
    mode = values.get("mode")
    links = [Link("ai_embedding", "Embedding")]
    if mode in ("load", "retrieve", "retrieve-as-tool") and bool(values.get("useReranker")):
        links.append(Link("ai_reranker", "Reranker"))
    if mode == "retrieve-as-tool":
        return links
    if mode in ("insert", "load", "update"):
        links.append(Link(MAIN))
    if mode == "insert":
        links.append(Link("ai_document", "Document"))
    return links


ONE_OR_FALLBACK: Final = "then Fallback when options.fallbackOutput is extra"
RULES: Final[Mapping[str, Rule]] = {
    "b9096695cd8e23bd": Rule(
        "Switch 3 to 3.4",
        "One exit for each of rules.values, named by its outputKey or else its number from 0, "
        f"{ONE_OR_FALLBACK}. With mode expression, numberOutputs exits named 0, 1 and so on.",
        _switch,
    ),
    "94623a3d61c069b7": Rule(
        "Switch 2",
        "One exit for each of rules.rules, named by its outputKey or else its number from 0. "
        "With mode expression, outputsAmount exits named 0, 1 and so on.",
        _switch_2,
    ),
    "45be92cb24032b60": Rule(
        "Merge 3 to 3.2",
        "numberInputs main inputs, 2 if it isn't set: Input 1, Input 2 and so on, which are "
        "inputs 0, 1 and so on.",
        _merge,
    ),
    "79260d56022774e8": Rule(
        "Webhook", "One exit for each HTTP method it listens to, named by the method.", _webhook
    ),
    "3e5f54fc58d1dc0e": Rule(
        "Respond to Webhook",
        "One exit, main, or Input Data and Response at version 1.3, or from 1.4 when "
        "enableResponseOutput is true.",
        _respond,
    ),
    "69eddba38d99fddb": Rule(
        "Text Classifier",
        "One exit for each category, named by it, then Other when options.fallback is other.",
        _classes,
    ),
    "cfdfa4624a8bdbf8": Rule(
        "Sentiment Analysis",
        "One exit for each of options.categories, by default Positive, Neutral and Negative.",
        _sentiment,
    ),
    "a329c6a60639ffdd": Rule(
        "Guardrails 1 and 2",
        "Pass and Fail when operation is classify, else one exit, main.",
        _guardrails,
    ),
    "c4bf57067c1a171d": Rule(
        "Guardrails 2",
        "One main input, and a Chat Model input when a check uses a model: each is input 0 "
        "of its kind.",
        _guardrails_takes,
    ),
    "b88ad595ab1d5197": Rule(
        "Guardrails 1",
        "One main input, and a Chat Model input unless operation is sanitize: each is input "
        "0 of its kind.",
        _guardrails_1_takes,
    ),
    "c397b35d8c9c993f": Rule(
        "Evaluation",
        "Evaluation and Normal when operation is checkIfEvaluating, else one exit, main.",
        _evaluation,
    ),
    "199a00bd5cca585c": Rule(
        "Evaluation",
        "One main input, and a Model input for the correctness and helpfulness metrics: each "
        "is input 0 of its kind.",
        _evaluation_takes,
    ),
    "b2a7b0db1ea36814": Rule(
        "The vector stores",
        "By mode: ai_vectorStore for retrieve, ai_tool for retrieve-as-tool, else main.",
        _vector_store,
    ),
    "00d35c0066cacf74": Rule(
        "The vector stores",
        "An Embedding input, a main input for insert, load and update, and a Document input "
        "for insert: each is input 0 of its kind.",
        _vector_store_takes,
    ),
}
BY_HAND: Final[Mapping[str, Hand]] = {
    "cb12c0076d8dd306": Hand("AI Agent 1 to 1.9", main=1),
    "ac86e7c70276354d": Hand("AI Agent 2 to 3.1", main=1),
    "66798647ba00a381": Hand("AI Agent Tool", main=0),
    "7c1b94452bdcb44f": Hand("Microsoft Agent 365 Trigger", main=0),
    "81adf3772a265db8": Hand("Basic LLM Chain", main=1),
    "df6a34b762ca8f29": Hand("Summarization Chain 2 and 2.1", main=1),
    "7c4b7a8a065360e0": Hand("Chat", main=1),
    "0e8b55ee39b103d5": Hand("Chat Trigger", main=0),
    "38a63e9a93775cee": Hand("Structured Output Parser", main=0),
    "c76ccaff4803fb52": Hand("Default Data Loader and GitHub Document Loader", main=0),
    "2163497c9785898a": Hand("Model Selector", main=0),
    "86d2ea0f7baa9f27": Hand("OpenAI", main=1),
    "29121dbbc2b650e6": Hand("Anthropic, Google Gemini and Ollama", main=1),
    "28877ceda89014b1": Hand("Qwen Cloud, MiniMax and Moonshot Kimi", main=1),
}
