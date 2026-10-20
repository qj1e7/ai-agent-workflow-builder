from collections.abc import Mapping, Sequence
from typing import NoReturn

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict

type Json = str | int | float | bool | None | Mapping[str, Json] | Sequence[Json]


class WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def not_implemented() -> NoReturn:
    raise HTTPException(status_code=501, detail="Not implemented yet")
