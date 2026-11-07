from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from platform_api.auth import OPERATORS_ONLY, SIGNED_IN, CurrentPrincipal
from platform_api.builder.http import Operator
from platform_api.builder.lifecycle import TooLate
from platform_api.builder.models import (
    AddressIn,
    AddSoftware,
    FindIn,
    FindOut,
    ScheduleIn,
    WatchlistOut,
    WatchlistView,
)
from platform_api.builder.watchlist import (
    NeverAtThatAddress,
    NoMoveReported,
    NoSuchSoftware,
    NoWatchlist,
    RepoAddedAgainSinceRemoval,
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


def _full(limit: int) -> HTTPException:
    problem = {
        "type": "watchlist_full",
        "loc": ["body"],
        "msg": f"The watchlist holds {limit} software at most",
    }
    return HTTPException(422, [problem])


@router.post(
    "/watchlist/find",
    description=(
        "Finds the GitHub projects a software's plain name could mean. The agent runtime looks "
        "the name up in a reviewed list, never through a model, and asks GitHub about each "
        "match with the watchlist's own tag rule before offering it. Nothing is saved: the "
        "person picks a match, then adds it with POST /watchlist/software. A match that is "
        "already watched says so."
    ),
    responses=OPERATORS_ONLY,
)
async def find_software(body: FindIn, principal: Operator, watchlist: CurrentWatchlist) -> FindOut:
    return await watchlist.find(body.name)


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
            raise _full(limit)


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


@router.post(
    "/watchlist/software/{software_id}/restore",
    description=(
        "Puts removed software back on the watchlist as it was, with the same id, so what the "
        "platform learned about it comes back too, within a day of the removal. Software "
        "already on the list stays as it is."
    ),
    responses={
        **OPERATORS_ONLY,
        404: error_response("This software was never on the watchlist"),
        409: error_response("The repository was added again after it was removed"),
        410: error_response("The software was removed more than a day ago"),
    },
)
async def restore_software(
    software_id: str, principal: Operator, watchlist: CurrentWatchlist
) -> WatchlistView:
    match await watchlist.restore(SoftwareId(software_id)):
        case WatchlistView() as restored:
            return restored
        case NoSuchSoftware():
            raise HTTPException(404, "This software was never on the watchlist")
        case TooLate():
            raise HTTPException(
                410, "This software was removed more than a day ago, so it can't be put back."
            )
        case RepoAddedAgainSinceRemoval(ref):
            raise HTTPException(
                409,
                f"{ref} was added again after it was removed, so the removed entry cannot come "
                "back",
            )
        case WatchlistFull(limit):
            raise _full(limit)


@router.post(
    "/watchlist/software/{software_id}/address",
    description=(
        "Replaces the saved repository of one software with the one GitHub reported at the "
        "latest check (moved_to on the row), after the person confirmed it. The body names the "
        "address the person saw. A new version of the list is saved, so every later check reads "
        "the new address. Only the watchlist changes: nothing is written to GitHub or Jira. "
        "Asking again for the address already saved changes nothing."
    ),
    responses={
        **OPERATORS_ONLY,
        404: error_response("No such watched software"),
        409: error_response(
            "GitHub has not reported that address for this software, or the list already watches it"
        ),
    },
)
async def use_new_address(
    software_id: str, body: AddressIn, principal: Operator, watchlist: CurrentWatchlist
) -> WatchlistView:
    match await watchlist.use_new_address(principal, SoftwareId(software_id), body.repo):
        case WatchlistView() as switched:
            return switched
        case NoSuchSoftware():
            raise HTTPException(404, "No such watched software")
        case NoMoveReported():
            raise HTTPException(
                409, "GitHub has not reported that address for this software at the latest check"
            )
        case RepoAlreadyWatched(ref):
            raise HTTPException(409, f"{ref} is already watched")


@router.post(
    "/watchlist/software/{software_id}/address/undo",
    description=(
        "Puts back the address a software had before the new one was used, within a day of the "
        "switch, as the restore of a removal does. The body names the address to put back. "
        "Asking for the address already saved changes nothing."
    ),
    responses={
        **OPERATORS_ONLY,
        404: error_response("No such watched software"),
        409: error_response("The software never had that address, or the list now watches it"),
        410: error_response("The address was switched more than a day ago"),
    },
)
async def put_address_back(
    software_id: str, body: AddressIn, principal: Operator, watchlist: CurrentWatchlist
) -> WatchlistView:
    match await watchlist.put_address_back(principal, SoftwareId(software_id), body.repo):
        case WatchlistView() as back:
            return back
        case NoSuchSoftware():
            raise HTTPException(404, "No such watched software")
        case NeverAtThatAddress(ref):
            raise HTTPException(409, f"This software was never at {ref}")
        case RepoAlreadyWatched(ref):
            raise HTTPException(409, f"{ref} is already watched")
        case TooLate():
            raise HTTPException(
                410, "The address was changed more than a day ago, so it can't be put back."
            )


@router.put(
    "/watchlist/schedule",
    description=(
        "Saves when the watchlist is checked on its own. The caller becomes the schedule "
        "owner, who can never approve a scheduled check."
    ),
    responses={**OPERATORS_ONLY, 404: error_response("The watchlist does not exist yet")},
)
async def save_schedule(
    body: ScheduleIn, principal: Operator, watchlist: CurrentWatchlist
) -> WatchlistView:
    match await watchlist.save_schedule(principal, body):
        case WatchlistView() as saved:
            return saved
        case NoWatchlist():
            raise HTTPException(404, "Add software first, then set the schedule")


@router.delete(
    "/watchlist/schedule",
    description="Turns the schedule off. Checks then start only when an Operator starts one.",
    responses={**OPERATORS_ONLY, 404: error_response("The watchlist does not exist yet")},
)
async def turn_off_schedule(principal: Operator, watchlist: CurrentWatchlist) -> WatchlistView:
    match await watchlist.turn_off_schedule():
        case WatchlistView() as left:
            return left
        case NoWatchlist():
            raise HTTPException(404, "Add software first, then set the schedule")
