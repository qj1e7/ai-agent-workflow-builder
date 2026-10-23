import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import quote

from platform_api.shared import RunId, TaskId


@dataclass(frozen=True)
class Callback:
    url: str
    token: str


def callback_for(
    key: str, platform_internal_url: str, run_id: RunId, task_id: TaskId, expires_at: datetime
) -> Callback:
    expires = int(expires_at.timestamp())
    task = quote(task_id, safe="")
    url = f"{platform_internal_url}/internal/v1/runs/{run_id}/agent-events?task={task}"
    return Callback(url, f"{expires}.{_signature(key, run_id, task_id, expires)}")


def verify_callback(key: str, run_id: RunId, task_id: TaskId, token: str, now: datetime) -> bool:
    expires_text, dot, signature = token.partition(".")
    if dot != "." or not expires_text.isdigit():
        return False
    expires = int(expires_text)
    if int(now.timestamp()) >= expires:
        return False
    return hmac.compare_digest(signature, _signature(key, run_id, task_id, expires))


def _signature(key: str, run_id: RunId, task_id: TaskId, expires: int) -> str:
    message = f"{run_id}|{task_id}|{expires}".encode()
    return hmac.new(key.encode(), message, hashlib.sha256).hexdigest()
