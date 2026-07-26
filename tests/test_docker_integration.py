from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from smartcli.execution import DockerExecutionBackend, ExecutionRequest

pytestmark = pytest.mark.skipif(
    os.getenv("SMARTCLI_DOCKER_TEST") != "1",
    reason="set SMARTCLI_DOCKER_TEST=1 to run the opt-in Docker integration test",
)


def test_docker_backend_executes_in_networkless_disposable_container(tmp_path: Path):
    image = os.getenv("SMARTCLI_DOCKER_IMAGE", "python:3.11-slim")
    container_name = "smartcli-integration-cleanup"
    result = DockerExecutionBackend(name_factory=lambda: container_name).run(
        ExecutionRequest(
            command=(
                "python",
                "-c",
                "from pathlib import Path; Path('docker-result.txt').write_text('ok')",
            ),
            workspace=tmp_path,
            timeout_seconds=30,
            environment={},
            image=image,
        )
    )
    assert result.success, f"{result.error_type}: {result.stderr}"
    assert result.backend == "docker"
    assert (tmp_path / "docker-result.txt").read_text(encoding="utf-8") == "ok"
    inspected = subprocess.run(
        ["docker", "inspect", container_name], capture_output=True, check=False
    )
    assert inspected.returncode != 0
