# Agent Engineering Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add project policy, Local/Docker execution backends, evidence-based verification, run telemetry, and an offline deterministic evaluation framework to SmartCLI 0.9.0.

**Architecture:** `ProjectCheckTool` delegates process execution to an `ExecutionBackend`; CLI loads a restrictive `ProjectPolicy` and wires the backend into tools. `ReActAgent` emits model/tool telemetry, while `VerificationCollector` derives completion evidence from persisted action order. The eval runner uses disposable fixture copies and deterministic graders over the same run-report schema.

**Tech Stack:** Python 3.11+, stdlib `tomllib`, dataclasses, subprocess/Docker CLI, argparse, pytest, Ruff.

## Global Constraints

- Preserve default read-only Agent behavior and explicit `--allow` authority.
- Repository policy may constrain but never expand CLI authority.
- Docker uses argument arrays, network `none`, no privileged mode, no Docker socket, and no Local fallback.
- Default CI performs no paid model call, Docker daemon call, or network request.
- Telemetry records no prompt, file body, API key, or checkpoint content.
- Existing hash-guarded writes, checkpoints, undo, JSON envelopes, Python 3.11+, and Windows/Linux support remain compatible.

---

### Task 1: Repository Policy

**Files:**
- Create: `src/smartcli/policy.py`
- Create: `tests/test_policy.py`

**Interfaces:**
- Produces: `PolicyError`, `ExecutionPolicy`, `WorkspacePolicy`, `ChecksPolicy`, `ProjectPolicy`, and `load_project_policy(workspace: Path) -> ProjectPolicy`.
- `ProjectPolicy` fields: `execution`, `workspace`, and `checks`.
- Default policy uses Local backend, no image, network `none`, timeout 120, memory 512, CPU 1.0, PIDs 128, allowed checks `tests/lint/compile`, and no required checks.

- [ ] **Step 1: Write failing policy tests**

```python
def test_policy_defaults_and_valid_docker_config(tmp_path):
    assert load_project_policy(tmp_path).execution.backend == "local"
    (tmp_path / "smartcli.toml").write_text(
        '[execution]\nbackend="docker"\nimage="project:test"\nnetwork="none"\n'
        '[checks]\nallowed=["tests"]\nrequired=["tests"]\n', encoding="utf-8"
    )
    policy = load_project_policy(tmp_path)
    assert policy.execution.image == "project:test"
    assert policy.checks.required == ("tests",)

def test_policy_rejects_unknown_keys_network_and_missing_image(tmp_path):
    for value, message in [
        ('[execution]\nunknown=true\n', "unknown"),
        ('[execution]\nnetwork="bridge"\n', "network"),
        ('[execution]\nbackend="docker"\n', "image"),
    ]:
        (tmp_path / "smartcli.toml").write_text(value, encoding="utf-8")
        with pytest.raises(PolicyError, match=message):
            load_project_policy(tmp_path)
```

- [ ] **Step 2: Run `python -m pytest tests/test_policy.py -v` and confirm import failure.**

- [ ] **Step 3: Implement frozen dataclasses and strict TOML parsing.** Validate table/key sets, numeric ranges (`timeout_seconds` 1–600, `memory_mb` 64–32768, `cpus` 0.1–64, `pids_limit` 16–4096), known checks, required subset of allowed, `backend` in `local/docker`, Docker image presence, and `network == "none"`.

- [ ] **Step 4: Run policy tests and `python -m ruff check src/smartcli/policy.py tests/test_policy.py`.**

- [ ] **Step 5: Commit `feat: add restrictive project policy`.**

### Task 2: Execution Backend and Check Refactor

**Files:**
- Create: `src/smartcli/execution/__init__.py`
- Create: `src/smartcli/execution/base.py`
- Create: `src/smartcli/execution/local.py`
- Create: `src/smartcli/execution/docker.py`
- Modify: `src/smartcli/tools/checks.py`
- Modify: `src/smartcli/cli.py`
- Create: `tests/test_execution.py`
- Modify: `tests/test_tools.py`

**Interfaces:**
- Produces `ExecutionRequest(command, workspace, timeout_seconds, environment, network, memory_mb, cpus, pids_limit, image)` and `ExecutionResult(exit_code, stdout, stderr, elapsed_ms, timed_out, backend, error_type=None)`.
- Produces `ExecutionBackend.run(request)`, `LocalExecutionBackend`, `DockerExecutionBackend`, and `backend_from_policy(policy) -> ExecutionBackend`.
- `ProjectCheckTool(backend: ExecutionBackend, policy: ProjectPolicy)` returns metadata containing `check`, `exit_code`, `backend`, `elapsed_ms`, and `timed_out`.

- [ ] **Step 1: Write backend contract tests.** Assert Local passes an argument array with no `shell`, filters `OPENAI_API_KEY`, measures elapsed time, and classifies timeout. Assert Docker builds arguments containing `--network none`, `--memory 512m`, `--cpus 1.0`, `--pids-limit 128`, `no-new-privileges`, exactly one workspace mount, and no `docker.sock`/home/API key.

- [ ] **Step 2: Run `python -m pytest tests/test_execution.py -v` and confirm missing-module failure.**

- [ ] **Step 3: Implement base dataclasses/protocol and Local backend.** Use `time.monotonic`, `subprocess.run`, UTF-8 replacement decoding, `shell=False` by omission, and stable `timeout/start_error/nonzero` result metadata.

- [ ] **Step 4: Implement Docker backend.** Resolve Docker outside the workspace with `shutil.which`, construct `docker run --rm --network none --security-opt no-new-privileges --memory ... --cpus ... --pids-limit ... --mount type=bind,source=<workspace>,target=/workspace -w /workspace <image> <command...>`, and never retry with Local.

- [ ] **Step 5: Refactor `ProjectCheckTool`.** Keep the three existing check mappings, enforce `policy.checks.allowed`, clamp timeout to both tool argument and policy maximum, create `ExecutionRequest`, and map `ExecutionResult` to `ToolResult`.

- [ ] **Step 6: Wire `_agent_tools(allowed, policy, backend)` in CLI and update existing mocked check tests.**

- [ ] **Step 7: Run `python -m pytest tests/test_execution.py tests/test_tools.py tests/test_cli.py -v` and Ruff.**

- [ ] **Step 8: Commit `feat: add local and Docker execution backends`.**

### Task 3: Telemetry and Provider Usage

**Files:**
- Create: `src/smartcli/telemetry.py`
- Modify: `src/smartcli/services/llm.py`
- Modify: `src/smartcli/agent/runner.py`
- Modify: `src/smartcli/runs.py`
- Create: `tests/test_telemetry.py`
- Modify: `tests/test_llm.py`
- Modify: `tests/test_agent.py`

**Interfaces:**
- Produces `TokenUsage(prompt_tokens, completion_tokens, total_tokens)`, `TelemetryCollector`, `record_model`, `record_tool`, `record_protocol_error`, `record_denial`, `finish`, and `to_dict`.
- Extends `ResponseText` with `duration_ms: int` and `usage: TokenUsage | None`.
- `ReActAgent(..., telemetry: TelemetryCollector | None = None)` records every model attempt, protocol failure, denial, and executed tool duration.

- [ ] **Step 1: Write failing tests.** Mock provider `usage` and monotonic clock; assert `ResponseText.usage.total_tokens`, duration, retries, tool milliseconds, protocol count, and redacted serializable telemetry dictionary.

- [ ] **Step 2: Run telemetry/LLM/Agent tests and confirm failures.**

- [ ] **Step 3: Implement telemetry dataclasses and collector.** Store only integer counts, durations, booleans, tool/check names, and backend names; never accept prompt/content arguments.

- [ ] **Step 4: Extend LLM adapter.** Measure the whole adapter request including retries and parse `response.usage.prompt_tokens`, `completion_tokens`, and `total_tokens` only when all are integers; otherwise set usage to `None`.

- [ ] **Step 5: Instrument ReActAgent.** Time model calls and tools, record `ResponseText` attempts/usage, protocol errors, approval denials, tool results, and finalize in both success and step-limit paths.

- [ ] **Step 6: Add `RunJournal.set_telemetry(value: dict[str, Any])` and persist telemetry before completion/failure.** Telemetry write failure follows the existing warning semantics and never reverses completed actions.

- [ ] **Step 7: Run targeted tests and Ruff.**

- [ ] **Step 8: Commit `feat: record Agent telemetry and token usage`.**

### Task 4: Evidence-Based Verification

**Files:**
- Create: `src/smartcli/verification.py`
- Modify: `src/smartcli/runs.py`
- Modify: `src/smartcli/cli.py`
- Modify: `src/smartcli/agent/runner.py`
- Create: `tests/test_verification.py`
- Modify: `tests/test_runs.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Produces `CheckEvidence`, `VerificationSummary`, and `build_verification(actions: list[dict], changes: list[dict], required_checks: tuple[str, ...]) -> VerificationSummary`.
- Qualifying checks must appear after the last successful file change action.
- Status values are `verified`, `partially_verified`, `failed`, and `unverified`.

- [ ] **Step 1: Write the verification state matrix tests.** Cover no checks, all required passing, one required missing, required failure, optional-only pass, and a successful check invalidated by a later write.

- [ ] **Step 2: Run `python -m pytest tests/test_verification.py -v` and confirm import failure.**

- [ ] **Step 3: Implement immutable evidence models and chronological reducer.** Use action indexes and metadata `check/backend/exit_code`; changed files come from applied run changes and are sorted/deduplicated.

- [ ] **Step 4: Persist verification in `RunJournal.complete(..., verification)` and expose it through public reports.**

- [ ] **Step 5: Add verification evidence to the final-step Agent state.** The runner receives a `verification_provider: Callable[[], dict]` and appends a machine-generated evidence block; it does not rewrite model output.

- [ ] **Step 6: Add verification to Agent JSON and plain output.** Plain stderr prints `Verification: <status>`; JSON `data.verification` uses `to_dict()`.

- [ ] **Step 7: Run targeted tests and Ruff.**

- [ ] **Step 8: Commit `feat: derive verification from tool evidence`.**

### Task 5: Offline Deterministic Evaluation Framework

**Files:**
- Create: `src/smartcli/evals/__init__.py`
- Create: `src/smartcli/evals/models.py`
- Create: `src/smartcli/evals/graders.py`
- Create: `src/smartcli/evals/runner.py`
- Create: `tests/test_evals.py`
- Modify: `src/smartcli/cli.py`

**Interfaces:**
- Produces `EvalCase.from_path`, `Grade`, `EvalCaseResult`, `EvalReport`, `grade_case(case, workspace, run_report)`, and `EvalRunner.run(path) -> EvalReport`.
- Scripted offline cases use `decisions: list[dict]` in `case.json`; real-model execution requires explicit `--model` and is not used by CI.

- [ ] **Step 1: Write failing case/grader tests.** Build a temporary case with fixture, required/forbidden paths, contains predicates, maximum steps, and scripted final decision. Assert strict schema errors and deterministic pass/fail reasons.

- [ ] **Step 2: Run eval tests and confirm missing-module failure.**

- [ ] **Step 3: Implement strict eval models.** Validate paths remain below case root, capabilities are from `write/git/check`, maximum steps 1–100, graders use explicit contains/does-not-contain predicates, and case IDs match `[a-z][a-z0-9_-]{1,63}`.

- [ ] **Step 4: Implement deterministic graders.** Grade run status, verification, expected/forbidden changed paths, file predicates, maximum steps, and permission violations; return named grade entries and an aggregate pass flag.

- [ ] **Step 5: Implement offline runner.** Copy each fixture with `shutil.copytree` into `TemporaryDirectory`, use scripted decisions through the real `ReActAgent`, auto-confirm only declared capabilities, and write JSON/Markdown reports below `SMARTCLI_EVALS_PATH` or the user data directory.

- [ ] **Step 6: Add `smartcli eval run PATH [--model PROFILE] [--json]` and `eval report ID`.** Default mode requires scripted decisions; real model mode is explicit.

- [ ] **Step 7: Run eval and CLI tests, confirming no network/Docker call in offline mode.**

- [ ] **Step 8: Commit `feat: add deterministic Agent evaluation framework`.**

### Task 6: Release Integration and Documentation

**Files:**
- Modify: `README.md`
- Modify: `PRODUCT_DESIGN.md`
- Modify: `TECHNICAL_ARCHITECTURE.md`
- Modify: `AGENT_PROTOCOL.md`
- Modify: `pyproject.toml`
- Modify: `src/smartcli/__init__.py`
- Modify: `.github/workflows/ci.yml`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Version becomes `0.9.0` in project metadata and package version.
- Documentation includes a complete `smartcli.toml`, Local/Docker trust boundary, verification states, telemetry schema, offline eval case, and Docker opt-in test command.

- [ ] **Step 1: Add CLI contract tests for `0.9.0`, policy errors, verification JSON, eval JSON, and Docker-backend selection without fallback.**

- [ ] **Step 2: Run CLI tests and confirm version/documentation-related failures.**

- [ ] **Step 3: Update version and all four technical/product documents.** Remove obsolete statements that checks are only Local and mark Agent Engineering Core delivered.

- [ ] **Step 4: Extend CI with the offline eval smoke case.** Do not install/start Docker and do not configure model API keys.

- [ ] **Step 5: Run `python -m pytest`, `python -m ruff check .`, `python -m compileall -q src tests`, `python -m build --no-isolation`, `python -m pip check`, `smartcli --version`, and `git diff --check`.**

- [ ] **Step 6: Inspect the built wheel and run `smartcli eval --help`, `smartcli agent --help`, and an offline eval smoke command from the installed entry point.**

- [ ] **Step 7: Commit `feat: release Agent engineering core 0.9.0`.**

