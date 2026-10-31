"""The throwaway PostgreSQL container leaves no Docker volume behind (issue #114).

The test looks only at the volumes of the container it starts, so tests running at the same time
on the same Docker cannot change its answer.
"""

import json
import shutil
import subprocess

import pytest

from tests.conftest import POSTGRES_IMAGE, throwaway_postgres


def _docker(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["docker", *args], capture_output=True, text=True, check=False)


def _volumes_of(container: str) -> list[str]:
    inspected = _docker("container", "inspect", "--format", "{{json .Mounts}}", container)
    assert inspected.returncode == 0, inspected.stderr
    mounts = json.loads(inspected.stdout)
    return [mount["Name"] for mount in mounts if mount["Type"] == "volume"]


def test_the_throwaway_postgres_container_leaves_no_volume_behind() -> None:
    if shutil.which("docker") is None:
        pytest.skip("needs Docker")
    if _docker("image", "inspect", POSTGRES_IMAGE).returncode != 0:
        pytest.skip("the pinned PostgreSQL image is not on this machine, and this test pulls none")

    with throwaway_postgres() as container:
        used = _volumes_of(container)

    assert _docker("container", "inspect", container).returncode != 0, "the container is still up"
    left = [volume for volume in used if _docker("volume", "inspect", volume).returncode == 0]
    assert left == [], f"the container left its volumes behind: {left}"
