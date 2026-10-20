import json
import shutil
from pathlib import Path

from platform_api.app import create_app
from platform_api.contracts.stories import fixtures
from platform_api.monitoring.events import activity_event_adapter
from platform_api.wire import WireModel

GENERATOR_ENV = {
    "AUTH_MODE": "dev",
    "PUBLIC_BASE_URL": "http://localhost:8000",
    "DATABASE_URL_BUILDER": "postgresql://wab_builder:x@localhost/platform",
    "DATABASE_URL_ORCHESTRATION": "postgresql://wab_orchestration:x@localhost/platform",
    "DATABASE_URL_MONITORING": "postgresql://wab_monitoring:x@localhost/platform",
    "AGENT_RUNTIME_URL": "http://agent-runtime:8100",
    "AGENT_API_KEY": "generator",
    "N8N_BASE_URL": "http://n8n:5678",
    "STEP_KEY": "generator",
    "PLATFORM_INTERNAL_URL": "http://platform-api:8000",
    "CALLBACK_SIGNING_KEY": "generator",
}
OWNED_FIXTURE_DIRS = (
    "runs",
    "views",
    "approvals",
    "builder",
    "internal",
    "stubs",
    "troubleshooting",
)


def _dump(value: WireModel | list[WireModel]) -> object:
    if isinstance(value, list):
        return [item.model_dump(mode="json") for item in value]
    return value.model_dump(mode="json")


def _write_json(path: Path, value: object, sort_keys: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=sort_keys) + "\n")


def write_all(root: Path) -> list[Path]:
    written: list[Path] = []
    openapi = root / "openapi.json"
    _write_json(openapi, create_app(GENERATOR_ENV).openapi(), sort_keys=True)
    written.append(openapi)
    schema = root / "activity-event.schema.json"
    _write_json(schema, activity_event_adapter.json_schema(), sort_keys=True)
    written.append(schema)
    fixture_root = root / "fixtures"
    for name in OWNED_FIXTURE_DIRS:
        shutil.rmtree(fixture_root / name, ignore_errors=True)
    for relative, value in fixtures().items():
        path = fixture_root / relative
        _write_json(path, _dump(value))
        written.append(path)
    return written
