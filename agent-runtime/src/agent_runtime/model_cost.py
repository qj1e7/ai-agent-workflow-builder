"""What one model call costs, from its token counts and a price in `pricing.json`'s shape. The
eval's spend cap and a fix's cost count price calls the same way, from the one price table the
runtime ships (ADR 0055, PR 5), so a fix's cost count works outside the evals too."""

import json
from collections.abc import Mapping
from functools import cache
from pathlib import Path
from typing import Any, Final, cast

CACHE_WRITES: Final = ("cache_creation", "ephemeral_5m_input_tokens", "ephemeral_1h_input_tokens")
PRICES: Final = Path(__file__).with_name("pricing.json")
"""The price table, by `provider:model`. It is package data, so it is in the runtime image."""


@cache
def packaged_prices() -> dict[str, Mapping[str, Any]]:
    """The price table the runtime ships, by `provider:model`."""
    return cast(dict[str, Mapping[str, Any]], json.loads(PRICES.read_text()))


def cached_tokens(usage: Mapping[str, Any]) -> tuple[int, int]:
    """The input tokens a call read from the prompt cache, and those it wrote to it."""
    details = cast(Mapping[str, Any], usage.get("input_token_details") or {})
    read = int(details.get("cache_read") or 0)
    written = sum(int(details.get(key) or 0) for key in CACHE_WRITES)
    return read, written


def dollars_for(
    tokens_in: float, tokens_out: float, read: float, written: float, price: Mapping[str, Any]
) -> float:
    """A call's cost at `price`. Cached input costs the model's cache prices when
    `pricing.json` names them, and the fresh input price when it doesn't."""
    fresh = price["input_usd_per_mtok"]
    cost = (tokens_in - read - written) * fresh + tokens_out * price["output_usd_per_mtok"]
    cost += read * price.get("cache_read_usd_per_mtok", fresh)
    cost += written * price.get("cache_write_usd_per_mtok", fresh)
    return cost / 1_000_000
