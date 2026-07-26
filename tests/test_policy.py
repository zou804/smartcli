from __future__ import annotations

import pytest

from smartcli.policy import PolicyError, load_project_policy


def test_policy_defaults_and_valid_docker_config(tmp_path):
    default = load_project_policy(tmp_path)
    assert default.execution.backend == "local"
    assert default.execution.network == "none"
    assert default.checks.allowed == ("tests", "lint", "compile")
    assert default.checks.required == ()

    (tmp_path / "smartcli.toml").write_text(
        """[execution]
backend = "docker"
image = "project:test"
network = "none"
timeout_seconds = 90
memory_mb = 768
cpus = 2.0
pids_limit = 64

[workspace]
writable = ["src/**", "tests/**"]
protected = ["migrations/**"]

[checks]
allowed = ["tests", "lint"]
required = ["tests"]
""",
        encoding="utf-8",
    )
    policy = load_project_policy(tmp_path)
    assert policy.execution.image == "project:test"
    assert policy.execution.timeout_seconds == 90
    assert policy.workspace.can_write("src/app.py")
    assert not policy.workspace.can_write("migrations/001.py")
    assert policy.checks.required == ("tests",)


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("[execution]\nunknown=true\n", "unknown"),
        ('[execution]\nnetwork="bridge"\n', "network"),
        ('[execution]\nbackend="docker"\n', "image"),
        ('[execution]\ntimeout_seconds=0\n', "timeout_seconds"),
        ('[checks]\nallowed=["tests"]\nrequired=["lint"]\n', "required"),
        ('[workspace]\nwritable=["../outside/**"]\n', "workspace.writable"),
        ("unexpected=1\n", "root"),
    ],
)
def test_policy_rejects_unsafe_or_unknown_values(tmp_path, value, message):
    (tmp_path / "smartcli.toml").write_text(value, encoding="utf-8")
    with pytest.raises(PolicyError, match=message):
        load_project_policy(tmp_path)
