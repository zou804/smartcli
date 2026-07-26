from __future__ import annotations

import subprocess
from pathlib import Path

from smartcli.execution import (
    DockerExecutionBackend,
    ExecutionRequest,
    LocalExecutionBackend,
)


class Completed:
    returncode = 0
    stdout = "ok"
    stderr = ""


def request(tmp_path: Path, **overrides) -> ExecutionRequest:
    values = {
        "command": ("python", "-m", "pytest"),
        "workspace": tmp_path,
        "timeout_seconds": 30,
        "environment": {"PATH": "bin", "OPENAI_API_KEY": "secret"},
        "network": "none",
        "memory_mb": 512,
        "cpus": 1.0,
        "pids_limit": 128,
        "image": None,
    }
    values.update(overrides)
    return ExecutionRequest(**values)


def test_local_backend_runs_argument_array_with_reduced_environment(tmp_path):
    captured = {}
    ticks = iter((1.0, 1.125))

    def fake_run(command, **kwargs):
        captured.update(command=command, kwargs=kwargs)
        return Completed()

    result = LocalExecutionBackend(runner=fake_run, clock=lambda: next(ticks)).run(
        request(tmp_path)
    )
    assert result.success and result.backend == "local" and result.elapsed_ms == 125
    assert captured["command"][0] != "python"
    assert captured["command"][1:] == ["-m", "pytest"]
    assert captured["kwargs"]["cwd"] == tmp_path
    environment = captured["kwargs"]["env"]
    assert environment["PATH"] == "bin"
    assert environment["PYTHONNOUSERSITE"] == "1"
    assert environment["PIP_DISABLE_PIP_VERSION_CHECK"] == "1"
    assert "OPENAI_API_KEY" not in environment
    assert "shell" not in captured["kwargs"]


def test_local_backend_classifies_timeout(tmp_path):
    def timeout(command, **kwargs):
        raise subprocess.TimeoutExpired(command, 3, output="partial", stderr="slow")

    result = LocalExecutionBackend(runner=timeout).run(
        request(tmp_path, timeout_seconds=3)
    )
    assert not result.success and result.timed_out
    assert result.error_type == "timeout" and result.stdout == "partial"


def test_docker_backend_constructs_isolated_command_without_fallback(tmp_path):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return Completed()

    result = DockerExecutionBackend(
        docker_executable="C:/tools/docker.exe",
        runner=fake_run,
        name_factory=lambda: "smartcli-test",
        container_user="1000:1000",
    ).run(request(tmp_path, image="project:test"))
    command = calls[0][0]
    joined = " ".join(command)
    assert result.success and result.backend == "docker"
    assert command[0] == "C:/tools/docker.exe"
    assert command[1:4] == ["create", "--name", "smartcli-test"]
    assert "--pull never" in joined
    assert "--network none" in joined
    assert "--memory 512m" in joined and "--cpus 1.0" in joined
    assert "--pids-limit 128" in joined
    assert "no-new-privileges" in joined and "--privileged" not in command
    assert "docker.sock" not in joined and "OPENAI_API_KEY" not in joined
    mounts = [command[index + 1] for index, item in enumerate(command) if item == "--mount"]
    assert len(mounts) == 1 and "target=/workspace" in mounts[0]
    assert command[-3:] == ["python", "-m", "pytest"]
    assert calls[1][0] == ["C:/tools/docker.exe", "start", "--attach", "smartcli-test"]
    assert calls[2][0] == ["C:/tools/docker.exe", "rm", "--force", "smartcli-test"]


def test_docker_backend_reports_missing_cli_without_running_local(tmp_path):
    called = False

    def forbidden(*args, **kwargs):
        nonlocal called
        called = True
        return Completed()

    result = DockerExecutionBackend(
        docker_executable=None, runner=forbidden, which=lambda name: None
    ).run(request(tmp_path, image="project:test"))
    assert not result.success and result.error_type == "docker_missing"
    assert called is False


def test_docker_backend_force_removes_container_after_timeout(tmp_path):
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if command[1] == "start":
            raise subprocess.TimeoutExpired(command, 3, output="partial", stderr="slow")
        return Completed()

    result = DockerExecutionBackend(
        docker_executable="docker",
        runner=fake_run,
        name_factory=lambda: "smartcli-timeout",
    ).run(request(tmp_path, image="project:test", timeout_seconds=3))
    assert result.timed_out and result.error_type == "timeout"
    assert calls[-1] == ["docker", "rm", "--force", "smartcli-timeout"]


def test_docker_backend_refuses_root_host_identity(tmp_path, monkeypatch):
    monkeypatch.setattr("smartcli.execution.docker.os.getuid", lambda: 0, raising=False)
    monkeypatch.setattr("smartcli.execution.docker.os.getgid", lambda: 0, raising=False)
    called = False

    def forbidden(*args, **kwargs):
        nonlocal called
        called = True
        return Completed()

    result = DockerExecutionBackend(docker_executable="docker", runner=forbidden).run(
        request(tmp_path, image="project:test")
    )
    assert not result.success and result.error_type == "root_host_user"
    assert called is False
