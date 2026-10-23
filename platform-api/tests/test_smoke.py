import importlib

import pytest


@pytest.mark.parametrize("context", ["builder", "orchestration", "monitoring"])
def test_context_package_imports(context):
    assert importlib.import_module(f"platform_api.{context}")
