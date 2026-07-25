from __future__ import annotations

from smartcli.config import ConfigManager
from smartcli.doctor import run_doctor


def test_doctor_is_offline_by_default(tmp_path):
    manager = ConfigManager(tmp_path / "config.json")
    checks = run_doctor(manager, environ={"DEEPSEEK_API_KEY": "fake"})
    values = {check.name: check for check in checks}
    assert values["config"].status == "ok"
    assert values["api_key"].status == "ok"
    assert values["connection"].status == "skipped"


def test_doctor_reports_missing_key_and_skips_connection(tmp_path):
    manager = ConfigManager(tmp_path / "config.json")
    checks = run_doctor(manager, connect=True, environ={})
    values = {check.name: check for check in checks}
    assert values["api_key"].status == "error"
    assert values["connection"].status == "error"
