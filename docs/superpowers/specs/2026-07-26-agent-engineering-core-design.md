# SmartCLI Agent Engineering Core Design

## 1. Objective

Upgrade SmartCLI 0.8.0 from a safe local code-change Agent prototype into an interview-ready
Agent engineering system that demonstrates isolated execution, deterministic evaluation,
verification evidence, project policy, and operational telemetry.

The release target is 0.9.0. It must preserve the existing defaults: read-only Agent capability,
explicit authorization, redacted audit logs, hash-guarded writes, checkpoints, and safe undo.

## 2. Scope

This release delivers:

1. an `ExecutionBackend` protocol with Local and Docker implementations;
2. a typed `VerificationSummary` derived from actual tool evidence;
3. repository-level `smartcli.toml` policy that can constrain but never expand CLI authority;
4. run telemetry for model calls, tools, steps, retries, duration, and token usage when available;
5. an evaluation framework with isolated fixture copies and deterministic graders.

This release does not deliver GitHub API integration, multi-Agent orchestration, vector search,
arbitrary shell execution, dependency installation, or automatic Docker image builds.

## 3. Architecture

```text
CLI / Eval Runner
  -> ProjectPolicy
  -> ReActAgent
       -> AgentModelAdapter / LLMService
       -> ToolRegistry
            -> ProjectCheckTool
                 -> ExecutionBackend
                      |-- LocalBackend
                      `-- DockerBackend
       -> TelemetryCollector
       -> VerificationCollector
  -> RunJournal
  -> VerificationSummary / EvalReport
```

New modules:

```text
src/smartcli/
├── execution/
│   ├── __init__.py
│   ├── base.py
│   ├── local.py
│   └── docker.py
├── evals/
│   ├── __init__.py
│   ├── models.py
│   ├── graders.py
│   └── runner.py
├── policy.py
├── telemetry.py
└── verification.py
```

Each module owns one concern. `ProjectCheckTool` validates Agent arguments and translates a named
check into an `ExecutionRequest`; it no longer launches subprocesses directly. Eval execution uses
the same public Agent and tool path as normal CLI execution.

## 4. Execution Backends

### 4.1 Contracts

`ExecutionRequest` contains an argument array, workspace, timeout, environment allowlist,
network policy, and resource limits. It never contains shell command text.

`ExecutionResult` contains exit code, stdout, stderr, elapsed milliseconds, timeout state, backend
name, and resource-policy metadata. Output remains subject to the existing observation limit.

`ExecutionBackend` exposes one method:

```python
def run(self, request: ExecutionRequest) -> ExecutionResult: ...
```

### 4.2 Local Backend

The Local backend preserves current behavior while moving it behind the protocol. It invokes an
argument array with `shell=False`, uses the existing reduced environment, enforces timeout, and
marks the result as not OS-sandboxed.

### 4.3 Docker Backend

The Docker backend directly invokes the Docker CLI with a constructed argument array. It never
mounts the Docker socket, home directory, Git credentials, API keys, or paths outside the workspace.

Defaults:

- workspace bind-mounted at `/workspace`;
- working directory `/workspace`;
- network `none`;
- read/write workspace because checks may create caches and test artifacts;
- non-root container user selected by policy or image default when safely available;
- memory 512 MiB, 1 CPU, 128 PIDs, 120-second timeout;
- `--rm`, no privileged mode, no added capabilities, and `no-new-privileges`;
- no silent fallback to Local when Docker is unavailable.

The policy names a prebuilt image containing project dependencies. SmartCLI does not build images
or install dependencies in this release. Docker availability and image errors become stable typed
execution failures.

## 5. Project Policy

SmartCLI loads optional `smartcli.toml` from the workspace root. Unknown keys and invalid values
are errors. A repository policy may narrow runtime behavior but cannot grant a capability omitted
from CLI `--allow` flags.

Minimal schema:

```toml
[execution]
backend = "docker"
image = "smartcli-project:latest"
network = "none"
timeout_seconds = 120
memory_mb = 512
cpus = 1.0
pids_limit = 128

[workspace]
writable = ["src/**", "tests/**"]
protected = [".github/**", "migrations/**"]

[checks]
allowed = ["tests", "lint", "compile"]
required = ["tests", "lint"]
```

Precedence is: hard-coded safety invariant, then project policy, then CLI selection. CLI can choose
a stricter backend or lower limit but cannot disable a protected path or enable policy-forbidden
network access.

Version 0.9.0 supports only `network = "none"`. Any other value fails validation instead of
pretending to isolate network access.

## 6. Verification

`VerificationCollector` consumes actual action records, not model claims. It emits:

```json
{
  "status": "verified|partially_verified|failed|unverified",
  "required_checks": ["tests", "lint"],
  "checks": [
    {"name": "tests", "status": "passed", "exit_code": 0, "backend": "docker"}
  ],
  "changed_files": ["src/app.py"],
  "unverified": [],
  "risks": []
}
```

Rules:

- `verified`: every required check ran after the last file change and passed;
- `partially_verified`: at least one check passed but a required check is missing;
- `failed`: any required check failed after the last change;
- `unverified`: no qualifying check ran after the last change.

The CLI and JSON response display this summary. Run reports persist it. The final Agent prompt is
given the current evidence and instructed not to claim tests passed when the collector disagrees.

## 7. Telemetry

Telemetry is local and attached to `run_id`. It records no prompt or file body.

Metrics:

- total run duration;
- per-step model duration;
- model call and retry counts;
- prompt, completion, and total tokens when the provider reports usage;
- per-tool duration, success, and output truncation;
- protocol violation count;
- approval denial count;
- context-trimming count;
- selected execution backend.

If a provider omits usage, token fields are `null`; SmartCLI does not invent exact token counts.
Telemetry persistence failure is reported without changing a completed tool action into a failure.

## 8. Evaluation Framework

Eval cases are versioned JSON documents plus fixture directories:

```text
evals/cases/fix_config/
├── case.json
└── fixture/
```

`case.json` contains case ID, task, model profile, allowed capabilities, required checks, expected
changed paths, forbidden paths, maximum steps, and deterministic grading rules.

For each case the runner:

1. copies the fixture into a temporary workspace;
2. loads its project policy;
3. runs the real Agent with only case-declared capabilities;
4. auto-approves actions only inside that disposable fixture and only within declared capabilities;
5. grades the run report, verification summary, file hashes/content predicates, forbidden-path
   invariants, and step budget;
6. writes JSON and Markdown aggregate reports.

Initial deterministic graders:

- required check status;
- expected and forbidden changed paths;
- file contains / does-not-contain predicates;
- run status and maximum steps;
- permission violation count.

The suite supports scripted fake-model decisions for offline CI and real-model runs when explicitly
requested. Paid/network model calls are never part of default CI.

CLI surface:

```text
smartcli eval run PATH [--model PROFILE] [--json]
smartcli eval report REPORT_ID [--json]
```

## 9. Error Handling and Safety

- Docker missing, daemon unavailable, image missing, timeout, and non-zero exit are distinct states.
- Docker policy never silently downgrades to Local.
- Policy parsing errors identify the exact key.
- Eval fixture paths cannot escape the case directory.
- Auto-approval exists only inside copied temporary eval workspaces.
- Workspace policy cannot grant write, check, Git, shell, or network authority.
- Checkpoint and undo behavior remains unchanged for Agent file tools.
- Run and evaluation reports redact checkpoint bodies and model secrets.

## 10. Testing

Unit tests cover policy parsing and precedence, verification state transitions, telemetry aggregation,
ExecutionBackend contracts, Docker argument construction, error classification, graders, and report
serialization.

Integration tests run the Local backend. Docker integration tests are opt-in through an environment
flag and use a minimal pre-existing image; normal CI tests Docker construction with a mocked process
boundary and never requires a daemon.

Acceptance criteria:

- existing tests continue to pass;
- offline CI contains no model or Docker network request;
- a required check before the last file write does not count as verification;
- Docker policy cannot fall back to Local;
- project policy cannot expand CLI authority;
- eval reports are reproducible for scripted-model cases;
- Ruff, compileall, package build, wheel smoke test, and `pip check` pass.

## 11. Release and Documentation

The project version becomes 0.9.0. README documents Local versus Docker trust boundaries, policy
schema, verification statuses, telemetry fields, eval authoring, and an offline example. Product and
technical architecture documents are updated to mark Agent Engineering Core as delivered.

