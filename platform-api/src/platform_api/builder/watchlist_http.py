from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from platform_api.auth import OPERATORS_ONLY, SIGNED_IN, CurrentPrincipal
from platform_api.builder.http import Operator
from platform_api.builder.models import AddSoftware, WatchlistOut, WatchlistView
from platform_api.builder.watchlist import (
    NoSuchSoftware,
    RepoAlreadyWatched,
    Watchlist,
    WatchlistFull,
)
from platform_api.shared import SoftwareId
from platform_api.wire import error_response


def current_watchlist(request: Request) -> Watchlist:
    watchlist: Watchlist = request.app.state.watchlist
    return watchlist


CurrentWatchlist = Annotated[Watchlist, Depends(current_watchlist)]

router = APIRouter(prefix="/api/v1", tags=["builder"])


@router.get(
    "/watchlist",
    description="The team's watchlist, or null until the first software is added.",
    responses=SIGNED_IN,
)
async def get_watchlist(principal: CurrentPrincipal, watchlist: CurrentWatchlist) -> WatchlistOut:
    return WatchlistOut(watchlist=await watchlist.view())


@router.post(
    "/watchlist/software",
    status_code=201,
    description="Adds software to the watchlist, making the watchlist on the first add.",
    responses={**OPERATORS_ONLY, 409: error_response("This repository is already watched")},
)
async def add_software(
    body: AddSoftware, principal: Operator, watchlist: CurrentWatchlist
) -> WatchlistView:
    match await watchlist.add(principal, body):
        case WatchlistView() as added:
            return added
        case RepoAlreadyWatched(ref):
            raise HTTPException(409, f"{ref} is already watched")
        case WatchlistFull(limit):
            raise HTTPException(
                422, [{"loc": ["body"], "msg": f"The watchlist holds {limit} software at most"}]
            )


@router.delete(
    "/watchlist/software/{software_id}",
    responses={**OPERATORS_ONLY, 404: error_response("No such watched software")},
)
async def remove_software(
    software_id: str, principal: Operator, watchlist: CurrentWatchlist
) -> WatchlistView:
    match await watchlist.remove(SoftwareId(software_id)):
        case WatchlistView() as left:
            return left
        case NoSuchSoftware():
            raise HTTPException(404, "No such watched software")
