from __future__ import annotations

import os
from pathlib import Path

import pytest

from smartcli.execution import DockerExecutionBackend, ExecutionRequest

pytestmark = pytest.mark.skipif(
    os.getenv("SMARTCLI_DOCKER_TEST") != "1",
    reason="set SMARTCLI_DOCKER_TEST=1 to run the opt-in Docker integration test",
)


def test_docker_backend_executes_in_networkless_disposable_container(tmp_path: Path):
    image = os.getenv("SMARTCLI_DOCKER_IMAGE", "python:3.11-slim")
    result = DockerExecutionBackend().run(
        ExecutionRequest(
            command=("python", "-c", "print('smartcli-docker-ok')"),
            workspace=tmp_path,
            timeout_seconds=30,
            environment={},
            image=image,
        )
    )
    assert result.success, f"{result.error_type}: {result.stderr}"
    assert result.backend == "docker" and result.stdout.strip() == "smartcli-docker-ok"
