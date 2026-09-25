"""Provider-neutral, fail-closed model calls for PEWeaver.

This module is deliberately small and model-independent.  It owns routing,
budgets, idempotency, cooldowns, watchdog state, and a redacted audit ledger;
the evaluator remains outside this module and remains the authority for
candidate acceptance.  The default route is OpenCode and OpenRouter is
unavailable unless *both* runtime/CLI configuration and the explicit
``PEWEAVER_ALLOW_OPENROUTER_BILLABLE=1`` environment gate are present.

The production adapters are imported lazily.  Tests can provide a
``backend_factory`` and therefore never need credentials, Ray, a CLI, or a
network connection.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import queue
import signal
import subprocess
import threading
import time
import uuid
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal, Mapping, Protocol, Sequence


Role = Literal["lead", "worker"]


@dataclass(frozen=True)
class ModelRoute:
    provider: str
    model: str


LEAD_ROUTES: tuple[ModelRoute, ...] = (
    ModelRoute("opencode", "openai/gpt-5.6-sol"),
    ModelRoute("openrouter", "openai/gpt-5.6-sol"),
)
WORKER_ROUTES: tuple[ModelRoute, ...] = (
    ModelRoute("opencode", "opencode-go/deepseek-v4-flash"),
    ModelRoute("openrouter", "deepseek/deepseek-v4-flash"),
)

_KNOWN_PROVIDERS = frozenset({"opencode", "openrouter", "gemini"})


def _routes_from_env(name: str, default: tuple[ModelRoute, ...]) -> tuple[ModelRoute, ...]:
    """Parse ``provider/model`` pairs (first-slash split; models may contain slashes)."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    routes: list[ModelRoute] = []
    for part in raw.split(","):
        part = part.strip()
        provider, _, model = part.partition("/")
        if provider not in _KNOWN_PROVIDERS or not model:
            raise ValueError(f"invalid model route in {name}: {part!r}")
        routes.append(ModelRoute(provider, model))
    return tuple(routes) if routes else default


@dataclass(frozen=True)
class ModelRequest:
    """A bounded, auditable request.

    ``deadline`` is a wall-clock UNIX timestamp.  ``candidate_path`` and
    ``candidate_hash_reader`` are optional guards for the model-editing
    workflow; if supplied, a mutation blocks failover after an uncertain
    result.  The prompt is intentionally never written to the ledger.
    """

    run_id: str
    work_id: str
    request_id: str
    role: Role
    prompt: str
    context_hash: str
    candidate_hash: str = ""
    deadline: float = 0.0
    token_cap: int = 4096
    estimated_input_tokens: int = 1024
    candidate_path: str | None = None
    candidate_hash_reader: Callable[[], str] | None = field(default=None, repr=False, compare=False)

    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        work_id: str,
        role: Role,
        prompt: str,
        context_hash: str,
        candidate_hash: str = "",
        deadline: float = 0.0,
        token_cap: int = 4096,
        estimated_input_tokens: int = 1024,
        request_id: str | None = None,
        candidate_path: str | None = None,
        candidate_hash_reader: Callable[[], str] | None = None,
    ) -> "ModelRequest":
        return cls(run_id, work_id, request_id or uuid.uuid4().hex, role, prompt,
                   context_hash, candidate_hash, deadline, token_cap,
                   estimated_input_tokens, candidate_path, candidate_hash_reader)


@dataclass(frozen=True)
class ModelUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0

    @classmethod
    def from_value(cls, value: Any) -> "ModelUsage | None":
        if value is None:
            return None
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            return None
        def integer(*names: str) -> int:
            for name in names:
                try:
                    return max(0, int(value.get(name, 0) or 0))
                except (TypeError, ValueError):
                    continue
            return 0
        try:
            cost = float(value.get("cost_usd", value.get("cost", 0.0)) or 0.0)
        except (TypeError, ValueError):
            cost = 0.0
        inp = integer("input_tokens", "prompt_tokens")
        out = integer("output_tokens", "completion_tokens")
        total = integer("total_tokens") or inp + out
        return cls(inp, out, total, max(0.0, cost))


@dataclass(frozen=True)
class ModelResponse:
    run_id: str
    work_id: str
    request_id: str
    role: Role
    provider: str = ""
    model: str = ""
    attempt: int = 0
    status: str = "failed"
    output: str = ""
    output_hash: str = ""
    context_hash: str = ""
    candidate_hash: str = ""
    deadline: float = 0.0
    token_cap: int = 0
    error: str = ""
    usage: ModelUsage | None = None
    elapsed_seconds: float = 0.0
    failover: bool = False

    @property
    def success(self) -> bool:
        return self.status == "succeeded"

    def public_dict(self) -> dict[str, Any]:
        result = asdict(self)
        if self.usage is not None:
            result["usage"] = asdict(self.usage)
        return result


@dataclass(frozen=True)
class ModelStatus:
    run_id: str
    request_id: str
    state: str
    provider: str = ""
    model: str = ""
    attempt: int = 0
    started_at: float = 0.0
    last_progress_at: float = 0.0
    deadline: float = 0.0
    cancel_requested: bool = False
    committed_candidate_mutation: bool = False
    error: str = ""
    role: Role = "worker"


@dataclass(frozen=True)
class BudgetStatus:
    run_id: str
    calls: int
    token_count: int
    spend_usd: float
    campaign_cap_usd: float
    role_cap_usd: float
    role_spend_usd: float
    calls_remaining: int
    tokens_remaining: int
    exhausted: bool
    reserved_usd: float = 0.0


@dataclass(frozen=True)
class ShimConfig:
    """Non-secret policy knobs; all limits are finite by construction."""

    openrouter_cli_opt_in: bool = False
    openrouter_runtime_opt_in: bool = False
    env_gate: str = "PEWEAVER_ALLOW_OPENROUTER_BILLABLE"
    campaign_cap_usd: float = 15.0
    lead_cap_usd: float = 5.0
    worker_cap_usd: float = 10.0
    max_calls_per_run: int = 8
    max_tokens_per_run: int = 65536
    transient_attempts: int = 2
    provider_cooldown_seconds: float = 30.0
    default_deadline_seconds: float = 600.0
    openrouter_input_rate_usd_per_1k_tokens: float = 0.03
    openrouter_output_rate_usd_per_1k_tokens: float = 0.06
    ledger_path: Path | None = None
    # OpenCode is restricted by default.  A controller must explicitly provide
    # an isolated staging directory if it needs a tool-enabled campaign.
    opencode_work_dir: Path | None = None
    opencode_bin: str = "opencode"
    prefer_chia_opencode: bool = False
    prefer_chia_openrouter: bool = False
    opencode_lead_variant: str = "high"
    opencode_worker_variant: str = "low"
    lead_routes: tuple[ModelRoute, ...] = LEAD_ROUTES
    worker_routes: tuple[ModelRoute, ...] = WORKER_ROUTES
    opencode_permissions: Mapping[str, str] = field(default_factory=lambda: {
        "edit": "deny", "bash": "deny", "webfetch": "deny",
        "external_directory": "deny",
    })

    @classmethod
    def from_environment(cls, *, cli_opt_in: bool = False) -> "ShimConfig":
        def flag(name: str) -> bool:
            return os.environ.get(name, "").strip() == "1"
        def number(name: str, default: str, cast: Callable[[str], Any]) -> Any:
            try:
                return cast(os.environ.get(name, default))
            except (TypeError, ValueError):
                return cast(default)
        return cls(
            openrouter_cli_opt_in=cli_opt_in,
            openrouter_runtime_opt_in=flag("PEWEAVER_OPENROUTER_RUNTIME_OPT_IN"),
            campaign_cap_usd=number("PEWEAVER_MODEL_CAMPAIGN_CAP_USD", "15", float),
            lead_cap_usd=number("PEWEAVER_MODEL_LEAD_CAP_USD", "5", float),
            worker_cap_usd=number("PEWEAVER_MODEL_WORKER_CAP_USD", "10", float),
            max_calls_per_run=number("PEWEAVER_MODEL_MAX_CALLS", "8", int),
            max_tokens_per_run=number("PEWEAVER_MODEL_MAX_TOKENS", "65536", int),
            ledger_path=Path(os.environ["PEWEAVER_MODEL_LEDGER"])
            if os.environ.get("PEWEAVER_MODEL_LEDGER") else None,
            opencode_work_dir=Path(os.environ["PEWEAVER_MODEL_WORK_DIR"])
            if os.environ.get("PEWEAVER_MODEL_WORK_DIR") else None,
            opencode_bin=os.environ.get("OPENCODE_BIN", "opencode"),
            prefer_chia_opencode=flag("PEWEAVER_PREFER_CHIA_OPENCODE"),
            prefer_chia_openrouter=flag("PEWEAVER_PREFER_CHIA_OPENROUTER"),
            opencode_lead_variant=os.environ.get("PEWEAVER_OPENCODE_LEAD_VARIANT", "high"),
            opencode_worker_variant=os.environ.get("PEWEAVER_OPENCODE_WORKER_VARIANT", "low"),
            lead_routes=_routes_from_env("PEWEAVER_LEAD_ROUTES", LEAD_ROUTES),
            worker_routes=_routes_from_env("PEWEAVER_WORKER_ROUTES", WORKER_ROUTES),
        )

    @property
    def openrouter_enabled(self) -> bool:
        return (self.openrouter_cli_opt_in and self.openrouter_runtime_opt_in
                and os.environ.get(self.env_gate) == "1")

    @property
    def gemini_enabled(self) -> bool:
        return bool(os.environ.get("GEMINI_API_KEY", "").strip())

    def role_cap(self, role: Role) -> float:
        return self.lead_cap_usd if role == "lead" else self.worker_cap_usd


class Backend(Protocol):
    def prompt(self, user_message: str, tools: Sequence[Any] | None = None) -> Any: ...


def _role_permissions(role: Role) -> dict[str, str]:
    """Deny-by-default OpenCode policy with the smallest role allowlist."""
    permissions = {"*": "deny", "read": "allow", "glob": "allow",
                   "grep": "allow", "list": "allow"}
    if role == "worker":
        permissions["edit"] = "allow"
    return permissions


class _SubprocessOpenCodeBackend:
    """Ray-free local OpenCode adapter with a killable process group.

    It uses only the OpenCode CLI, an isolated ``--dir`` and a temporary
    restrictive config. No environment or credential values are copied into
    logs or responses. The response is bounded to the requested token cap as
    a final defense; the config also supplies the model option when supported
    by the installed OpenCode version.
    """

    _peweaver_token_cap_supported = True

    def __init__(self, route: ModelRoute, *, work_dir: Path, binary: str,
                 timeout_seconds: float, permissions: Mapping[str, str], variant: str):
        self.route = route
        self.work_dir = work_dir
        self.binary = binary
        self.timeout_seconds = timeout_seconds
        self.permissions = dict(permissions)
        self.variant = variant
        self._proc: subprocess.Popen[str] | None = None
        self._lock = threading.RLock()
        self._role: Role = "lead"

    def set_role(self, role: Role) -> None:
        self._role = role

    def permission_config(self) -> dict[str, str]:
        return _role_permissions(self._role)

    def build_config(self, token_cap: int) -> dict[str, Any]:
        permissions = self.permission_config()
        return {
            "$schema": "https://opencode.ai/config.json",
            "permission": permissions,
            "agent": {"chia": {"mode": "primary",
                                  "options": {"maxOutputTokens": token_cap},
                                  "permission": permissions}},
        }

    def prompt(self, user_message: str, *, token_cap: int = 4096) -> dict[str, Any]:
        if not self.work_dir.is_dir() or self.work_dir.is_symlink():
            return {"success": False, "error": "invalid_staging_directory"}
        config_path = self.work_dir / ".peweaver-opencode-config.json"
        config = self.build_config(token_cap)
        # This file is inside the isolated staging directory and contains no
        # credentials. Restrictive mode prevents another local user from
        # reading or rewriting it during the call.
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
        xdg_config = self.work_dir / ".peweaver-xdg-config"
        try:
            xdg_config.mkdir(mode=0o700, exist_ok=True)
            os.chmod(xdg_config, 0o700)
            fd = os.open(config_path, flags, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(config, stream, sort_keys=True)
            env = {"OPENCODE_CONFIG": str(config_path),
                   "OPENCODE_DISABLE_PROJECT_CONFIG": "1",
                   "XDG_CONFIG_HOME": str(xdg_config)}
            # The CLI still needs its normal runtime environment for locating
            # binaries and its own credential store; never persist that env.
            env = dict(os.environ, **env)
            command = self.build_command(user_message)
            with self._lock:
                self._proc = subprocess.Popen(command, cwd=self.work_dir, env=env,
                                              text=True, stdout=subprocess.PIPE,
                                              stderr=subprocess.PIPE, start_new_session=True)
                proc = self._proc
            try:
                stdout, stderr = proc.communicate(timeout=self.timeout_seconds)
            except subprocess.TimeoutExpired:
                self._kill_process(proc)
                return {"success": False, "error": "stalled"}
            finally:
                with self._lock:
                    self._proc = None
            if proc.returncode != 0:
                # Classify the CLI's own failure text so the router can shift
                # to the next configured route: exhausted credits/rate limits
                # mean this provider cannot serve the call now (failover),
                # while an unusable key is a provider-level problem (also
                # failover).  Anything else is a hard provider error.
                text = (stdout or "") + "\n" + (stderr or "")
                lowered = text.lower()
                if any(sig in lowered for sig in (
                        "rate limit", "rate_limit", "quota", "credit", "credits",
                        "billing", "payment", "subscription", "insufficient",
                        "limit reached", "429", "402")):
                    return {"success": False, "error": "rate_or_quota"}
                if any(sig in lowered for sig in (
                        "401", "403", "unauthorized", "invalid api key",
                        "api key", "authentication", "forbidden")):
                    return {"success": False, "error": "provider_unavailable"}
                return {"success": False, "error": "provider_error"}
            output, usage = self._extract_output_usage(stdout)
            if not output:
                return {"success": False, "error": "empty_response"}
            # Approximate tokens conservatively for a final response bound;
            # the provider/config option remains the primary bound.
            words = output.split()
            output = " ".join(words[:max(1, token_cap)])
            return {"success": True, "output": output, "usage": usage}
        except FileNotFoundError:
            return {"success": False, "error": "provider_unavailable"}
        except (OSError, ValueError):
            return {"success": False, "error": "provider_error"}
        finally:
            try:
                config_path.unlink()
            except OSError:
                pass

    def cancel(self) -> bool:
        with self._lock:
            proc = self._proc
        if proc is None or proc.poll() is not None:
            return False
        return self._kill_process(proc)

    def build_command(self, user_message: str) -> list[str]:
        return [self.binary, "--pure", "run", "--format", "json", "--agent", "chia",
                "--model", self.route.model, "--variant", self.variant,
                "--dir", str(self.work_dir), user_message]

    @staticmethod
    def _kill_process(proc: subprocess.Popen[str]) -> bool:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
            return True
        except (ProcessLookupError, PermissionError, OSError):
            return False

    @staticmethod
    def _extract_output_usage(stdout: str) -> tuple[str, dict[str, Any] | None]:
        chunks: list[str] = []
        input_tokens = output_tokens = 0
        cost_usd = 0.0
        usage_seen = False
        for line in stdout.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            part = event.get("part") or {}
            text = part.get("text") or event.get("text")
            if isinstance(text, str):
                chunks.append(text)
            if event.get("type") == "step_finish" or "tokens" in part or "usage" in event:
                tokens = part.get("tokens") or event.get("tokens") or {}
                usage = event.get("usage") or {}
                def integer(*values: Any) -> int:
                    for value in values:
                        try:
                            return max(0, int(value or 0))
                        except (TypeError, ValueError):
                            continue
                    return 0
                input_tokens += integer(tokens.get("input"), tokens.get("prompt"), usage.get("input_tokens"), usage.get("prompt_tokens"))
                output_tokens += integer(tokens.get("output"), tokens.get("completion"), usage.get("output_tokens"), usage.get("completion_tokens"))
                try:
                    cost_usd += max(0.0, float(part.get("cost", event.get("cost", usage.get("cost", 0.0))) or 0.0))
                except (TypeError, ValueError):
                    pass
                usage_seen = usage_seen or bool(tokens or usage or "cost" in part or "cost" in event)
        if not usage_seen:
            return "".join(chunks), None
        return "".join(chunks), {"input_tokens": input_tokens, "output_tokens": output_tokens,
                                "total_tokens": input_tokens + output_tokens, "cost_usd": cost_usd}

    @staticmethod
    def _extract_text(stdout: str) -> str:
        """Compatibility helper for callers that only need streamed text."""
        return _SubprocessOpenCodeBackend._extract_output_usage(stdout)[0]


class _StdlibOpenRouterBackend:
    """Minimal OpenRouter client for hosts without CHIA/Ray installed."""

    _peweaver_token_cap_supported = True

    def __init__(self, route: ModelRoute, *, timeout_seconds: float):
        self.route = route
        self.timeout_seconds = timeout_seconds
        self.max_tokens = 4096

    def prompt(self, user_message: str, *, token_cap: int = 4096) -> dict[str, Any]:
        key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY")
        if not key:
            return {"success": False, "error": "authentication"}
        payload = json.dumps({"model": self.route.model,
                              "messages": [{"role": "user", "content": user_message}],
                              "max_tokens": token_cap}).encode("utf-8")
        request = urllib.request.Request(
            "https://openrouter.ai/api/v1/chat/completions", data=payload,
            headers={"Authorization": "Bearer " + key,
                     "Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                document = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            status = getattr(exc, "code", 0)
            return {"success": False, "error": "rate_or_quota" if status == 429 else
                    "billing" if status == 402 else "authentication" if status in (401, 403) else
                    "transient_server" if status >= 500 else "provider_error"}
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            return {"success": False, "error": "transient_server"}
        choices = document.get("choices") or []
        message = choices[0].get("message", {}) if choices and isinstance(choices[0], Mapping) else {}
        output = message.get("content", "") if isinstance(message, Mapping) else ""
        if not isinstance(output, str) or not output:
            return {"success": False, "error": "empty_response"}
        usage = document.get("usage") if isinstance(document, Mapping) else None
        if not isinstance(usage, Mapping):
            usage = None
        else:
            usage = {"input_tokens": usage.get("prompt_tokens", usage.get("input_tokens", 0)),
                     "output_tokens": usage.get("completion_tokens", usage.get("output_tokens", 0)),
                     "total_tokens": usage.get("total_tokens", 0),
                     "cost_usd": usage.get("cost", document.get("cost", 0.0))}
        return {"success": True, "output": output, "usage": usage}

    def cancel(self) -> bool:
        # urllib has no safe process/request cancellation primitive.
        return False


class _StdlibGeminiBackend:
    """Minimal Gemini Developer API client (stdlib only).

    Authentication and provider-level failures are reported as
    ``provider_unavailable`` so the router fails over to the next configured
    route instead of aborting the request: an unusable key means this
    provider cannot serve the call, which is exactly the shift-to-next-sub
    behavior the campaign expects. Cost accounting is zero by policy because
    this route is billed externally; token and call caps still bind.
    """

    _peweaver_token_cap_supported = True

    def __init__(self, route: ModelRoute, *, timeout_seconds: float):
        self.route = route
        self.timeout_seconds = timeout_seconds

    def prompt(self, user_message: str, *, token_cap: int = 4096) -> dict[str, Any]:
        key = os.environ.get("GEMINI_API_KEY", "")
        if not key:
            return {"success": False, "error": "provider_unavailable"}
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{self.route.model}:generateContent")
        payload = json.dumps({
            "contents": [{"role": "user", "parts": [{"text": user_message}]}],
            "generationConfig": {"maxOutputTokens": max(1, int(token_cap)),
                                 "temperature": 0.0,
                                 # Bound internal reasoning: 3.x flash models
                                 # otherwise spend the whole output budget on
                                 # thoughts and return MAX_TOKENS with no text.
                                 "thinkingConfig": {"thinkingBudget": 8192}},
        }).encode("utf-8")
        request = urllib.request.Request(
            url, data=payload,
            headers={"x-goog-api-key": key, "Content-Type": "application/json"},
            method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                document = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            status = getattr(exc, "code", 0)
            return {"success": False, "error": "rate_or_quota" if status == 429 else
                    "billing" if status == 402 else
                    "provider_unavailable" if status in (400, 401, 403, 404) else
                    "transient_server" if status >= 500 else "provider_error"}
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            return {"success": False, "error": "transient_server"}
        candidates = document.get("candidates") or []
        content = candidates[0].get("content", {}) if candidates and isinstance(candidates[0], Mapping) else {}
        parts = content.get("parts", []) if isinstance(content, Mapping) else []
        text = "".join(part.get("text", "") for part in parts
                       if isinstance(part, Mapping) and isinstance(part.get("text"), str))
        if not text.strip():
            reason = candidates[0].get("finishReason", "empty") if candidates else "empty"
            return {"success": False,
                    "error": "provider_error" if str(reason).upper() in ("MAX_TOKENS",) else "empty_response"}
        usage = document.get("usageMetadata") if isinstance(document, Mapping) else None
        if not isinstance(usage, Mapping):
            usage = None
        else:
            usage = {"input_tokens": int(usage.get("promptTokenCount", 0) or 0),
                     "output_tokens": int(usage.get("candidatesTokenCount", 0) or 0),
                     "total_tokens": int(usage.get("totalTokenCount", 0) or 0),
                     "cost_usd": 0.0}
        return {"success": True, "output": text, "usage": usage}

    def cancel(self) -> bool:
        return False


class _Failure:
    def __init__(self, code: str, failover: bool, retry: bool = False):
        self.code, self.failover, self.retry = code, failover, retry


class _CancelledCall(Exception):
    """Internal marker; never exposed in the ledger."""


class _UnkillableStall(Exception):
    """The synchronous adapter supplied no way to kill a timed-out call."""


class _TokenCapUnsupported(Exception):
    """An adapter cannot enforce the request's output-token bound."""


class ProviderNeutralModelShim:
    """Synchronous, deterministic provider router.

    A backend factory is preferred in tests and can also be used by a
    controller to isolate workers.  The default factory only constructs the
    existing Chia adapters when a call is actually authorized.
    """

    def __init__(
        self,
        config: ShimConfig | None = None,
        *,
        backend_factory: Callable[[ModelRoute], Backend] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.config = config or ShimConfig.from_environment()
        self._factory = backend_factory or self._default_backend
        self._clock = clock
        self._lock = threading.RLock()
        self._responses: dict[str, ModelResponse] = {}
        self._status: dict[str, ModelStatus] = {}
        self._cancel: dict[str, threading.Event] = {}
        self._cancel_verified: dict[str, bool] = {}
        self._backends: dict[ModelRoute, Backend] = {}
        self._cooldown_until: dict[ModelRoute, float] = {}
        self._calls: dict[str, int] = {}
        self._tokens: dict[str, int] = {}
        self._spend: dict[str, float] = {}
        self._reserved_spend: dict[str, float] = {}
        self._role_spend: dict[tuple[str, Role], float] = {}
        self._role_reserved: dict[tuple[str, Role], float] = {}

    # Required API -----------------------------------------------------

    def call(self, request: ModelRequest) -> ModelResponse:
        with self._lock:
            prior = self._responses.get(request.request_id)
            if prior is not None:
                return prior
            if request.role not in ("lead", "worker"):
                return self._finish(request, "invalid_request", error="invalid_role")
            if not request.prompt or not request.context_hash:
                return self._finish(request, "invalid_request", error="missing_request_field")
            deadline = request.deadline or self._clock() + self.config.default_deadline_seconds
            if request.token_cap <= 0:
                return self._finish(request, "budget_exhausted", error="invalid_token_cap", deadline=deadline)
            if self._clock() >= deadline:
                return self._finish(request, "deadline_exceeded", error="deadline_exceeded", deadline=deadline)
            if self._budget_blocked(request):
                return self._finish(request, "budget_exhausted", error="budget_exhausted", deadline=deadline)
            existing_cancel = self._cancel.get(request.request_id)
            if existing_cancel is not None and existing_cancel.is_set():
                return self._finish(request, "cancelled", error="cancelled", deadline=deadline)
            self._status[request.request_id] = ModelStatus(
                request.run_id, request.request_id, "running", deadline=deadline,
                started_at=self._clock(), last_progress_at=self._clock(), role=request.role)
            self._cancel[request.request_id] = existing_cancel or threading.Event()

        routes = self.config.lead_routes if request.role == "lead" else self.config.worker_routes
        eligible = [r for r in routes
                    if (r.provider != "openrouter" or self.config.openrouter_enabled)
                    and (r.provider != "gemini" or self.config.gemini_enabled)]
        if not eligible:
            return self._finish(request, "blocked", error="openrouter_requires_two_gates", deadline=deadline)

        last: ModelResponse | None = None
        for route_index, route in enumerate(eligible):
            now = self._clock()
            if self._cooldown_until.get(route, 0.0) > now:
                continue
            attempts = max(1, self.config.transient_attempts)
            for attempt in range(1, attempts + 1):
                if self._cancel[request.request_id].is_set():
                    return self._finish(request, "cancelled", error="cancelled", provider=route.provider,
                                        model=route.model, attempt=attempt, deadline=deadline)
                if self._clock() >= deadline:
                    return self._finish(request, "deadline_exceeded", error="deadline_exceeded",
                                        provider=route.provider, model=route.model, attempt=attempt, deadline=deadline)
                with self._lock:
                    if self._budget_blocked(request):
                        return self._finish(request, "budget_exhausted", error="budget_exhausted",
                                            provider=route.provider, model=route.model, attempt=attempt, deadline=deadline)
                    reservation = self._reserve(request, route)
                    if route.provider == "openrouter" and reservation is None:
                        return self._finish(request, "budget_exhausted", error="spend_reservation_exceeds_cap",
                                            provider=route.provider, model=route.model, attempt=attempt,
                                            deadline=deadline)
                    self._calls[request.run_id] = self._calls.get(request.run_id, 0) + 1
                    self._status[request.request_id] = ModelStatus(
                        request.run_id, request.request_id, "running", route.provider, route.model,
                        attempt, self._status[request.request_id].started_at, self._clock(), deadline,
                        role=request.role)
                try:
                    response = self._invoke(route, request, deadline)
                    if self._cancel[request.request_id].is_set():
                        verified = self._cancel_verified.get(request.request_id, False)
                        return self._finish(request, "cancelled" if verified else "ambiguous_completion",
                                            error="cancelled" if verified else "cancel_without_verified_kill",
                                            provider=route.provider, model=route.model,
                                            attempt=attempt, deadline=deadline)
                    result = self._adapt_response(request, route, attempt, response, deadline,
                                                  failover=route_index > 0)
                    if result.success:
                        with self._lock:
                            within_budget = self._account(request, result.usage, reservation=reservation)
                        if not within_budget:
                            return self._finish(request, "budget_exhausted", error="actual_spend_exceeded_cap",
                                                provider=route.provider, model=route.model, attempt=attempt,
                                                deadline=deadline, failover=route_index > 0)
                        return self._finish_response(result)
                    with self._lock:
                        self._release_reservation(request, reservation)
                    failure = self._failure_from_code(result.error or "backend_failed")
                except BaseException as exc:  # classify, never expose raw exception text
                    with self._lock:
                        self._release_reservation(request, reservation if "reservation" in locals() else None)
                    failure = self._classify(exc)
                    if failure.code == "cancelled":
                        verified = self._cancel_verified.get(request.request_id, False)
                        return self._finish(request, "cancelled" if verified else "ambiguous_completion",
                                            error="cancelled" if verified else "cancel_without_verified_kill",
                                            provider=route.provider, model=route.model,
                                            attempt=attempt, deadline=deadline)
                    result = self._finish(request, failure.code, error=failure.code,
                                          provider=route.provider,
                                          model=route.model, attempt=attempt, deadline=deadline,
                                          failover=route_index > 0)
                last = result
                if failure.code == "stalled":
                    # A timed-out worker may have completed remotely.  Only a
                    # verified unchanged candidate permits another route.
                    if not self._candidate_unchanged(request):
                        return self._finish(request, "ambiguous_completion",
                                            error="candidate_mutated_during_stall", provider=route.provider,
                                            model=route.model, attempt=attempt, deadline=deadline)
                    break
                if not failure.retry:
                    if failure.failover:
                        self._cooldown_until[route] = self._clock() + self.config.provider_cooldown_seconds
                    break
                self._cooldown_until[route] = self._clock() + self.config.provider_cooldown_seconds
            if last is not None and last.status in {"cancelled", "ambiguous_completion", "deadline_exceeded"}:
                return last
            if last is None or last.error not in {"rate_or_quota", "billing", "transient_server", "stalled", "provider_unavailable"}:
                return last or self._finish(request, "failed", error="backend_failed", deadline=deadline)
            # Failover is permitted only after an eligible failure and a clean
            # candidate guard.  Auth/invalid/evaluator failures stop above.
            if not self._candidate_unchanged(request):
                return self._finish(request, "candidate_mutation_blocked", error="candidate_mutated",
                                    deadline=deadline)
        return last or self._finish(request, "blocked", error="no_route_available", deadline=deadline)

    def status(self, request_id: str | None = None, *, run_id: str | None = None) -> ModelStatus | tuple[ModelStatus, ...]:
        with self._lock:
            if request_id is not None:
                return self._status.get(request_id, ModelStatus("", request_id, "unknown"))
            return tuple(v for v in self._status.values() if run_id is None or v.run_id == run_id)

    def cancel(self, request_id: str) -> ModelStatus:
        with self._lock:
            event = self._cancel.setdefault(request_id, threading.Event())
            current = self._status.get(request_id, ModelStatus("", request_id, "unknown"))
            verified = False
            if current.state == "running" and current.provider and current.model:
                backend = self._backends.get(ModelRoute(current.provider, current.model))
                cancel_backend = getattr(backend, "cancel", None) if backend is not None else None
                if callable(cancel_backend):
                    try:
                        verified = cancel_backend() is True
                    except Exception:
                        verified = False
            self._cancel_verified[request_id] = verified
            event.set()
            state = ("cancel_requested" if verified else "ambiguous_completion") if current.state == "running" else current.state
            updated = ModelStatus(current.run_id, current.request_id, state,
                                   current.provider, current.model, current.attempt, current.started_at,
                                   self._clock(), current.deadline, True, current.committed_candidate_mutation,
                                   current.error, current.role)
            self._status[request_id] = updated
            return updated

    def probe(self) -> dict[str, Any]:
        """Return policy reachability without constructing a backend or calling it."""
        return {"attempted": False, "openrouter_enabled": self.config.openrouter_enabled,
                "routes": {"lead": [asdict(r) for r in LEAD_ROUTES],
                           "worker": [asdict(r) for r in WORKER_ROUTES]},
                "status": "ready" if self.config.openrouter_enabled or os.environ.get(self.config.env_gate) != "1"
                else "blocked"}

    def budget(self, run_id: str) -> BudgetStatus:
        with self._lock:
            calls = self._calls.get(run_id, 0)
            tokens = self._tokens.get(run_id, 0)
            spend = self._spend.get(run_id, 0.0)
            # Campaign budget is the hard cap; role allocation is reported for
            # the caller's role through role_spend, and enforced per request.
            role_spend = max((v for (rid, _), v in self._role_spend.items() if rid == run_id), default=0.0)
            reserved = self._reserved_spend.get(run_id, 0.0)
            return BudgetStatus(run_id, calls, tokens, spend, self.config.campaign_cap_usd,
                                self.config.campaign_cap_usd, role_spend,
                                max(0, self.config.max_calls_per_run - calls),
                                max(0, self.config.max_tokens_per_run - tokens),
                                calls >= self.config.max_calls_per_run or tokens >= self.config.max_tokens_per_run
                                or spend + reserved >= self.config.campaign_cap_usd,
                                reserved)

    # Backend and safety internals ------------------------------------

    def _default_backend(self, route: ModelRoute) -> Backend:
        if route.provider == "opencode":
            if self.config.opencode_work_dir is None:
                # A non-staged OpenCode session can inspect the source tree;
                # refuse that unsafe default rather than silently broadening
                # the model's filesystem authority.
                raise RuntimeError("opencode_work_dir_required")
            if self.config.prefer_chia_opencode:
                try:
                    from chia.models.opencode import OpenCodeLLM
                    backend = OpenCodeLLM(
                        model=route.model,
                        timeout_seconds=int(self.config.default_deadline_seconds),
                        retries=1,
                        work_dir=str(self.config.opencode_work_dir),
                        dangerously_skip_permissions=False,
                        config=_role_permissions("lead" if "gpt-5.6" in route.model else "worker"),
                    )
                    # The bundled adapter has no per-request output cap.
                    backend._peweaver_token_cap_supported = False
                    return backend
                except (ImportError, ModuleNotFoundError):
                    pass
            return _SubprocessOpenCodeBackend(
                route, work_dir=self.config.opencode_work_dir,
                binary=self.config.opencode_bin,
                timeout_seconds=self.config.default_deadline_seconds,
                permissions=self.config.opencode_permissions,
                variant=(self.config.opencode_lead_variant if "gpt-5.6" in route.model
                          else self.config.opencode_worker_variant))
        if route.provider == "gemini":
            return _StdlibGeminiBackend(route, timeout_seconds=self.config.default_deadline_seconds)
        if route.provider == "openrouter":
            if self.config.prefer_chia_openrouter:
                try:
                    from chia.models.openai_providers import OpenRouterLLM
                    return OpenRouterLLM(model=route.model, timeout_seconds=int(self.config.default_deadline_seconds), retries=1)
                except (ImportError, ModuleNotFoundError):
                    pass
            return _StdlibOpenRouterBackend(route, timeout_seconds=self.config.default_deadline_seconds)
        raise RuntimeError("unknown_provider")

    def _invoke(self, route: ModelRoute, request: ModelRequest, deadline: float) -> Any:
        backend = self._backends.get(route)
        if backend is None:
            backend = self._factory(route)
            self._backends[route] = backend
        set_role = getattr(backend, "set_role", None)
        if callable(set_role):
            set_role(request.role)
        # OpenRouter exposes max_tokens on its OpenAI-compatible client.  Set
        # it for every request (the route backend is never shared concurrently
        # by this synchronous state machine).  OpenCode has no equivalent in
        # the bundled adapter; its default backend marks that limitation and
        # fails closed instead of treating a prompt instruction as a bound.
        setter = getattr(backend, "set_token_cap", None)
        if callable(setter):
            if setter(request.token_cap) is False:
                raise _TokenCapUnsupported()
        elif hasattr(backend, "max_tokens"):
            try:
                backend.max_tokens = request.token_cap
            except Exception:
                raise _TokenCapUnsupported()
        elif getattr(backend, "_peweaver_token_cap_supported", True) is False:
            raise _TokenCapUnsupported()
        # The adapters are synchronous.  A daemon watchdog thread lets a hard
        # stall return at the request deadline without keeping the controller
        # alive; the process group/evaluator remains the authority for killing
        # any model-side process.  A timed-out call is eligible for failover
        # only after the candidate guard succeeds in ``call``.
        result: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)
        def invoke() -> None:
            try:
                prompt = backend.prompt
                try:
                    parameters = inspect.signature(prompt).parameters
                    accepts_cap = "token_cap" in parameters or any(
                        parameter.kind == inspect.Parameter.VAR_KEYWORD
                        for parameter in parameters.values())
                except (TypeError, ValueError):
                    accepts_cap = False
                value = (prompt(request.prompt, token_cap=request.token_cap)
                         if accepts_cap else prompt(request.prompt))
                result.put((True, value), timeout=0.1)
            except BaseException as exc:
                try:
                    result.put((False, exc), timeout=0.1)
                except queue.Full:
                    pass
        thread = threading.Thread(target=invoke, name="peweaver-model-call", daemon=True)
        thread.start()
        while True:
            if self._cancel[request.request_id].is_set():
                raise _CancelledCall()
            remaining = deadline - self._clock()
            if remaining <= 0:
                # A timeout is failover-eligible only if the adapter confirms
                # that its underlying process was killed.  OpenCode wrappers
                # used by a reviewed controller may provide ``cancel``;
                # without it, completion is ambiguous and we stop.
                cancel_backend = getattr(backend, "cancel", None)
                if callable(cancel_backend):
                    try:
                        killed = cancel_backend()
                    except Exception:
                        killed = False
                    if killed is not False:
                        raise TimeoutError("model call deadline exceeded after kill")
                raise _UnkillableStall("model call deadline exceeded without kill")
            try:
                ok, value = result.get(timeout=min(0.05, remaining))
            except queue.Empty:
                continue
            if ok:
                return value
            raise value

    def _adapt_response(self, request: ModelRequest, route: ModelRoute, attempt: int,
                        raw: Any, deadline: float, *, failover: bool) -> ModelResponse:
        if isinstance(raw, ModelResponse):
            return raw
        output = getattr(raw, "result", None)
        if output is None and isinstance(raw, Mapping):
            output = raw.get("output", raw.get("result", ""))
        output = output if isinstance(output, str) else ""
        success = bool(getattr(raw, "success", None)) if not isinstance(raw, Mapping) else bool(raw.get("success", True))
        usage = ModelUsage.from_value(getattr(raw, "usage", None) if not isinstance(raw, Mapping) else raw.get("usage"))
        if usage is not None and usage.output_tokens > request.token_cap:
            return ModelResponse(request.run_id, request.work_id, request.request_id, request.role,
                                 route.provider, route.model, attempt, "output_limit_exceeded",
                                 "", "", request.context_hash, request.candidate_hash, deadline,
                                 request.token_cap, "token_cap_exceeded", usage,
                                 failover=failover)
        error = "" if success else (raw.get("error", "backend_failed") if isinstance(raw, Mapping)
                                     else "backend_failed")
        return ModelResponse(request.run_id, request.work_id, request.request_id, request.role,
                             route.provider, route.model, attempt, "succeeded" if success else "failed",
                             output, _hash_text(output) if output else "", request.context_hash,
                             request.candidate_hash, deadline, request.token_cap,
                             error, usage, failover=failover)

    @staticmethod
    def _failure_from_code(code: str) -> _Failure:
        if code in {"rate_or_quota", "billing"}:
            return _Failure(code, True)
        if code in {"stalled", "provider_unavailable", "transient_server", "empty_response"}:
            # An empty response means this provider served nothing usable;
            # the next configured route should get the call.
            return _Failure(code, True)
        return _Failure(code, False)

    def _classify(self, exc: BaseException) -> _Failure:
        name = type(exc).__name__.lower()
        module = type(exc).__module__.lower()
        code = getattr(exc, "status_code", None) or getattr(exc, "status", None)
        if "ambiguous" in name:
            return _Failure("ambiguous_completion", False)
        if isinstance(exc, _CancelledCall) or "cancelled" in name or "canceled" in name:
            return _Failure("cancelled", False)
        if isinstance(exc, _UnkillableStall):
            return _Failure("ambiguous_completion", False)
        if isinstance(exc, _TokenCapUnsupported):
            return _Failure("invalid_request", False)
        if "authentication" in name or "auth" in name or "invalidrequest" in name or "invalid_request" in name:
            return _Failure("authentication" if "auth" in name else "invalid_request", False)
        if "billing" in name or "quota" in name or code == 402:
            return _Failure("billing", True)
        if "ratelimit" in name or code == 429:
            return _Failure("rate_or_quota", True)
        if isinstance(exc, (TimeoutError,)) or "timeout" in name or "stall" in name:
            return _Failure("stalled", True)
        if isinstance(exc, ConnectionError) or (isinstance(exc, OSError) and not isinstance(exc, FileNotFoundError)) or "server" in name or (isinstance(code, int) and code >= 500):
            return _Failure("transient_server", True, retry=True)
        # Typed provider errors expose a stable ``error_type`` even when their
        # concrete class comes from a lazily imported module.
        typed = str(getattr(exc, "error_type", "")).lower()
        if typed in {"rate_limit", "billing_error"}:
            return _Failure("rate_or_quota" if typed == "rate_limit" else "billing", True)
        if typed == "server_error":
            return _Failure("transient_server", True, retry=True)
        return _Failure("provider_error", False)

    def _candidate_unchanged(self, request: ModelRequest) -> bool:
        if request.candidate_hash_reader is not None:
            try:
                return request.candidate_hash_reader() == request.candidate_hash
            except Exception:
                return False
        if request.candidate_path and request.candidate_hash:
            try:
                path = Path(request.candidate_path)
                # Never follow a model-created symlink while checking the
                # candidate guard; the hardened controller handles quarantine
                # and restoration of non-regular candidates.
                return (path.is_file() and not path.is_symlink()
                        and _hash_file(path) == request.candidate_hash)
            except OSError:
                return False
        return True

    def _budget_blocked(self, request: ModelRequest) -> bool:
        return (self._calls.get(request.run_id, 0) >= self.config.max_calls_per_run
                or self._tokens.get(request.run_id, 0) + request.token_cap > self.config.max_tokens_per_run
                or self._spend.get(request.run_id, 0.0) + self._reserved_spend.get(request.run_id, 0.0) >= self.config.campaign_cap_usd
                or self._role_spend.get((request.run_id, request.role), 0.0) + self._role_reserved.get((request.run_id, request.role), 0.0) >= self.config.role_cap(request.role))

    def _reserve(self, request: ModelRequest, route: ModelRoute) -> float | None:
        if route.provider != "openrouter":
            return 0.0
        input_tokens = max(0, request.estimated_input_tokens)
        estimate = ((input_tokens * self.config.openrouter_input_rate_usd_per_1k_tokens)
                    + (request.token_cap * self.config.openrouter_output_rate_usd_per_1k_tokens)) / 1000.0
        key = (request.run_id, request.role)
        if (self._spend.get(request.run_id, 0.0) + self._reserved_spend.get(request.run_id, 0.0) + estimate > self.config.campaign_cap_usd
                or self._role_spend.get(key, 0.0) + self._role_reserved.get(key, 0.0) + estimate > self.config.role_cap(request.role)):
            return None
        self._reserved_spend[request.run_id] = self._reserved_spend.get(request.run_id, 0.0) + estimate
        self._role_reserved[key] = self._role_reserved.get(key, 0.0) + estimate
        return estimate

    def _release_reservation(self, request: ModelRequest, reservation: float | None) -> None:
        if not reservation:
            return
        self._reserved_spend[request.run_id] = max(0.0, self._reserved_spend.get(request.run_id, 0.0) - reservation)
        key = (request.run_id, request.role)
        self._role_reserved[key] = max(0.0, self._role_reserved.get(key, 0.0) - reservation)

    def _account(self, request: ModelRequest, usage: ModelUsage | None, *, reservation: float | None) -> bool:
        # Unknown usage retains the reservation as a conservative charge. This
        # intentionally makes a later call stop at the cap rather than assume
        # that a paid provider call cost zero.
        if usage is None:
            return True
        self._release_reservation(request, reservation)
        self._tokens[request.run_id] = self._tokens.get(request.run_id, 0) + usage.total_tokens
        self._spend[request.run_id] = self._spend.get(request.run_id, 0.0) + usage.cost_usd
        key = (request.run_id, request.role)
        self._role_spend[key] = self._role_spend.get(key, 0.0) + usage.cost_usd
        return (self._spend[request.run_id] <= self.config.campaign_cap_usd
                and self._role_spend[key] <= self.config.role_cap(request.role))

    def _finish_response(self, result: ModelResponse) -> ModelResponse:
        with self._lock:
            self._responses[result.request_id] = result
            prior = self._status.get(result.request_id)
            self._status[result.request_id] = ModelStatus(
                result.run_id, result.request_id, result.status, result.provider, result.model,
                result.attempt, prior.started_at if prior else 0.0,
                self._clock(), result.deadline, prior.cancel_requested if prior else False,
                prior.committed_candidate_mutation if prior else False, result.error, result.role)
            self._append_ledger(result)
            return result

    def _finish(self, request: ModelRequest, status: str, *, error: str = "", provider: str = "",
                model: str = "", attempt: int = 0, deadline: float = 0.0,
                failover: bool = False) -> ModelResponse:
        result = ModelResponse(request.run_id, request.work_id, request.request_id, request.role,
                               provider, model, attempt, status, "", "", request.context_hash,
                               request.candidate_hash, deadline, request.token_cap, error,
                               None, failover=failover)
        return self._finish_response(result)

    def _append_ledger(self, result: ModelResponse) -> None:
        path = self.config.ledger_path
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "run_id": result.run_id, "work_id": result.work_id, "request_id": result.request_id,
            "role": result.role, "provider": result.provider, "model": result.model,
            "attempt": result.attempt, "status": result.status, "error": result.error,
            "context_hash": result.context_hash, "candidate_hash": result.candidate_hash,
            "output_hash": result.output_hash, "usage": asdict(result.usage) if result.usage else None,
            "failover": result.failover,
        }
        line = (json.dumps(entry, sort_keys=True, separators=(",", ":")) + "\n").encode()
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
        fd = os.open(path, flags, 0o600)
        try:
            os.write(fd, line)
            os.fsync(fd)
        finally:
            os.close(fd)


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# Friendly aliases used by controllers and tests.
ModelShim = ProviderNeutralModelShim
Request = ModelRequest
Response = ModelResponse
Config = ShimConfig
ModelShimConfig = ShimConfig
ModelCallRequest = ModelRequest
ModelCallResponse = ModelResponse

_default_instance: ProviderNeutralModelShim | None = None
_default_lock = threading.Lock()


def _default() -> ProviderNeutralModelShim:
    global _default_instance
    with _default_lock:
        if _default_instance is None:
            _default_instance = ProviderNeutralModelShim()
        return _default_instance


def call(request: ModelRequest, *, shim: ProviderNeutralModelShim | None = None) -> ModelResponse:
    """Module-level convenience API; no backend is constructed until called."""
    return (shim or _default()).call(request)


def status(request_id: str | None = None, *, run_id: str | None = None,
           shim: ProviderNeutralModelShim | None = None) -> ModelStatus | tuple[ModelStatus, ...]:
    return (shim or _default()).status(request_id, run_id=run_id)


def cancel(request_id: str, *, shim: ProviderNeutralModelShim | None = None) -> ModelStatus:
    return (shim or _default()).cancel(request_id)


def probe(*, shim: ProviderNeutralModelShim | None = None) -> dict[str, Any]:
    return (shim or _default()).probe()


def budget(run_id: str, *, shim: ProviderNeutralModelShim | None = None) -> BudgetStatus:
    return (shim or _default()).budget(run_id)


__all__ = [
    "BudgetStatus", "Config", "LEAD_ROUTES", "ModelCallRequest", "ModelCallResponse",
    "ModelShimConfig",
    "ModelRequest", "ModelResponse",
    "ModelRoute", "ModelShim", "ModelStatus", "ModelUsage", "ProviderNeutralModelShim",
    "Request", "Response", "ShimConfig", "WORKER_ROUTES", "budget", "call", "cancel", "probe", "status",
]
