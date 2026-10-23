import importlib

import pytest


def test_package_imports():
    assert importlib.import_module("agent_runtime")


def test_platform_api_is_not_importable():
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("platform_api")
