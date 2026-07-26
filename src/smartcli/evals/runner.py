"""Disposable-workspace runner for offline and explicitly online Agent evals."""

from __future__ import annotations

import json
import os
import shutil
import stat
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from platformdirs import user_data_path

from ..agent import ReActAgent
from ..execution import backend_from_policy
from ..policy import load_project_policy
from ..runs import RunStore
from ..services.llm import LLMService
from ..telemetry import TelemetryCollector
from ..tools import (
    ApplyPatchTool,
    GitTool,
    ListFilesTool,
    ProjectCheckTool,
    ReadFileTool,
    ToolRegistry,
    WriteFileTool,
)
from .graders import grade_case
from .models import EvalCase, EvalCaseError, EvalCaseResult, EvalReport


class _ScriptedLLM:
    def __init__(self, decisions: tuple[dict[str, Any], ...]) -> None:
        self.decisions = iter(decisions)

    def request(self, messages: object) -> str:
        try:
            return json.dumps(next(self.decisions), ensure_ascii=False)
        except StopIteration as exc:
            raise EvalCaseError("Scripted eval decisions were exhausted") from exc


class EvalRunner:
    def __init__(
        self,
        *,
        report_root: str | Path | None = None,
        model_name: str | None = None,
    ) -> None:
        override = os.getenv("SMARTCLI_EVALS_PATH")
        self.report_root = (
            Path(report_root)
            if report_root is not None
            else Path(override) if override else user_data_path("smartcli") / "evals"
        )
        self.model_name = model_name

    def run(self, path: str | Path) -> EvalReport:
        cases = [EvalCase.from_path(case_path) for case_path in _discover_cases(Path(path))]
        if not cases:
            raise EvalCaseError(f"No eval cases found below: {Path(path).resolve()}")
        results = tuple(self._run_case(case) for case in cases)
        report = EvalReport(
            report_id=(
                f"eval_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
            ),
            created_at=datetime.now(UTC).isoformat(),
            passed=all(case.passed for case in results),
            cases=results,
        )
        self._write_report(report)
        return report

    def _run_case(self, case: EvalCase) -> EvalCaseResult:
        with tempfile.TemporaryDirectory(prefix=f"smartcli-eval-{case.case_id}-") as temp:
            workspace = Path(temp) / "workspace"
            _reject_fixture_links(case.fixture)
            shutil.copytree(case.fixture, workspace, symlinks=True)
            policy = load_project_policy(workspace)
            if "check" in case.capabilities and policy.execution.backend != "docker":
                raise EvalCaseError(
                    "Unattended eval checks require the Docker backend; "
                    "Local checks can execute fixture code on the host"
                )
            backend = backend_from_policy(policy)
            tools = _tools(case, policy, backend)
            llm = LLMService(self.model_name) if self.model_name else _offline_llm(case)
            store = RunStore(Path(temp) / "runs")
            journal = store.start(workspace, case.task)
            telemetry = TelemetryCollector(execution_backend=policy.execution.backend)
            violations = [0]

            def record_violation(tool: str, reason: str) -> None:
                violations[0] += 1

            agent = ReActAgent(
                llm,
                tools,
                workspace=workspace,
                workspace_policy=policy.workspace,
                confirm=lambda tool, arguments, reason: _capability(tool) in case.capabilities,
                max_steps=case.max_steps,
                run_id=journal.run_id,
                before_action=journal.prepare_action,
                after_action=journal.record_action,
                telemetry=telemetry,
                verification_provider=lambda: journal.verification(
                    case.required_checks
                ).to_dict(),
                on_policy_violation=record_violation,
            )
            try:
                result = agent.run(case.task)
                verification = journal.verification(case.required_checks)
                if result.success:
                    journal.set_telemetry(telemetry.to_dict())
                    journal.complete(
                        final=result.final,
                        steps=result.steps,
                        plan=result.plan,
                        verification=verification,
                    )
                else:
                    journal.set_verification(verification)
                    journal.fail(result.final)
            except Exception as exc:
                verification = journal.verification(case.required_checks)
                journal.set_verification(verification)
                journal.fail(str(exc))
            report = store.get(journal.run_id)
            report["permission_violations"] = violations[0]
            grade = grade_case(case, workspace, report)
            steps = report.get("result", {}).get("steps", case.max_steps)
            return EvalCaseResult(
                case.case_id,
                grade.passed,
                grade.grades,
                report.get("verification") or verification.to_dict(),
                steps if isinstance(steps, int) else case.max_steps,
            )

    def get_report(self, report_id: str) -> dict[str, Any]:
        if not report_id.startswith("eval_") or any(char in report_id for char in "/\\"):
            raise EvalCaseError("Invalid eval report ID")
        try:
            value = json.loads(
                (self.report_root / f"{report_id}.json").read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise EvalCaseError(f"Cannot read eval report {report_id}: {exc}") from exc
        if not isinstance(value, dict) or value.get("report_id") != report_id:
            raise EvalCaseError(f"Invalid eval report: {report_id}")
        return value

    def _write_report(self, report: EvalReport) -> None:
        try:
            self.report_root.mkdir(parents=True, exist_ok=True)
            value = report.to_dict()
            (self.report_root / f"{report.report_id}.json").write_text(
                json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            lines = [
                f"# SmartCLI Eval Report {report.report_id}",
                "",
                f"Overall: {'PASS' if report.passed else 'FAIL'}",
                "",
            ]
            for case in report.cases:
                lines.append(f"- {'PASS' if case.passed else 'FAIL'} `{case.case_id}`")
            (self.report_root / f"{report.report_id}.md").write_text(
                "\n".join(lines) + "\n", encoding="utf-8"
            )
        except OSError as exc:
            raise EvalCaseError(f"Cannot write eval report: {exc}") from exc


def _discover_cases(path: Path) -> list[Path]:
    resolved = path.resolve()
    if resolved.is_file() and resolved.name == "case.json":
        return [resolved]
    if (resolved / "case.json").is_file():
        return [resolved / "case.json"]
    return sorted(resolved.glob("*/case.json")) if resolved.is_dir() else []


def _offline_llm(case: EvalCase) -> _ScriptedLLM:
    if not case.decisions:
        raise EvalCaseError(
            f"Eval case {case.case_id} has no scripted decisions; pass --model explicitly"
        )
    return _ScriptedLLM(case.decisions)


def _reject_fixture_links(fixture: Path) -> None:
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)

    def inspect(directory: Path) -> None:
        try:
            entries = list(os.scandir(directory))
        except OSError as exc:
            raise EvalCaseError(f"Cannot inspect eval fixture: {exc}") from exc
        for entry in entries:
            path = Path(entry.path)
            relative = path.relative_to(fixture).as_posix()
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise EvalCaseError(f"Cannot inspect eval fixture path {relative}: {exc}") from exc
            if entry.is_symlink():
                raise EvalCaseError(f"Eval fixture contains a symbolic link: {relative}")
            if getattr(info, "st_file_attributes", 0) & reparse_flag:
                raise EvalCaseError(f"Eval fixture contains a reparse point: {relative}")
            if entry.is_dir(follow_symlinks=False):
                inspect(path)

    inspect(fixture)


def _tools(case: EvalCase, policy: Any, backend: Any) -> ToolRegistry:
    tools: list[Any] = [ListFilesTool(), ReadFileTool()]
    if "write" in case.capabilities:
        tools.extend((WriteFileTool(), ApplyPatchTool()))
    if "git" in case.capabilities:
        tools.append(GitTool())
    if "check" in case.capabilities:
        tools.append(ProjectCheckTool(backend, policy))
    return ToolRegistry(tools)


def _capability(tool: str) -> str:
    return {
        "write_file": "write",
        "apply_patch": "write",
        "git": "git",
        "run_check": "check",
    }.get(tool, "read")
