"""opencode CLI LLM backend.

:class:`OpenCodeLLM` wraps the ``opencode`` CLI (https://opencode.ai) as an LLM
backend, opencode is provider-agnostic: the model is given as ``provider/model`` (e.g.
``anthropic/claude-sonnet-4-6``) and opencode runs its own server-side agentic
tool loop, so there is no client-side MCP loop here.

WARNING: experimental. Only exercised by the tests in
chia/models/tests/test_opencode.py (mocked unit tests, plus opt-in live tests).
Not validated in production. Auth is environment-driven: opencode uses its own
stored credentials (``opencode auth login``) or provider env vars.
"""

from __future__ import annotations

import json
import logging
import os
import re
import signal
import subprocess
import tempfile
import time as _time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import TYPE_CHECKING, Dict, List, Optional, Union

import ray

from chia.base.ChiaFunction import ChiaFunction
from chia.base.llm_call import QueryResult, LLMCallBase

if TYPE_CHECKING:
    from chia.base.tools.ChiaTool import ChiaTool


# ---------------------------------------------------------------------------
# Exceptions
#
# A parallel taxonomy to claude.py. Kept separate so this module stands alone;
# each carries ``__reduce__`` for Ray serialization.
# ---------------------------------------------------------------------------


class OpenCodeError(Exception):
    """Base for all opencode CLI errors."""

    def __init__(
        self,
        node_id: str,
        error_type: str,
        exit_code: int = -1,
        raw_message: str = "",
    ):
        self.node_id = node_id
        self.error_type = error_type
        self.exit_code = exit_code
        self.raw_message = raw_message
        super().__init__(f"{error_type} on {node_id}: {raw_message[:200]}")

    def __reduce__(self):
        return (
            self.__class__,
            (self.node_id, self.error_type, self.exit_code, self.raw_message),
        )


class RateLimitError(OpenCodeError):
    """The provider behind opencode reported a usage/rate limit."""

    def __init__(
        self,
        node_id: str,
        reset_time: datetime,
        raw_message: str = "",
        exit_code: int = -1,
    ):
        self.reset_time = reset_time
        super().__init__(node_id, "rate_limit", exit_code, raw_message)

    def __reduce__(self):
        return (
            self.__class__,
            (self.node_id, self.reset_time, self.raw_message, self.exit_code),
        )


class AuthenticationError(OpenCodeError):
    """opencode has no/invalid credentials for the selected provider."""

    def __init__(self, node_id: str, exit_code: int = -1, raw_message: str = ""):
        super().__init__(node_id, "authentication_failed", exit_code, raw_message)

    def __reduce__(self):
        return (self.__class__, (self.node_id, self.exit_code, self.raw_message))


class BillingError(OpenCodeError):
    """The provider account has a billing/payment problem."""

    def __init__(self, node_id: str, exit_code: int = -1, raw_message: str = ""):
        super().__init__(node_id, "billing_error", exit_code, raw_message)

    def __reduce__(self):
        return (self.__class__, (self.node_id, self.exit_code, self.raw_message))


class InvalidRequestError(OpenCodeError):
    """Malformed request — bad model string, invalid config, unknown agent, etc."""

    def __init__(self, node_id: str, exit_code: int = -1, raw_message: str = ""):
        super().__init__(node_id, "invalid_request", exit_code, raw_message)

    def __reduce__(self):
        return (self.__class__, (self.node_id, self.exit_code, self.raw_message))


class ServerError(OpenCodeError):
    """Transient provider/server-side failure (5xx, overloaded, connection)."""

    def __init__(
        self,
        node_id: str,
        exit_code: int = -1,
        raw_message: str = "",
        retry_after: Optional[int] = None,
    ):
        self.retry_after = retry_after
        super().__init__(node_id, "server_error", exit_code, raw_message)

    def __reduce__(self):
        return (
            self.__class__,
            (self.node_id, self.exit_code, self.raw_message, self.retry_after),
        )


class MaxOutputTokensError(OpenCodeError):
    """The response was truncated at the output token limit."""

    def __init__(
        self,
        node_id: str,
        exit_code: int = -1,
        raw_message: str = "",
        partial_text: str = "",
    ):
        self.partial_text = partial_text
        super().__init__(node_id, "max_output_tokens", exit_code, raw_message)

    def __reduce__(self):
        return (
            self.__class__,
            (self.node_id, self.exit_code, self.raw_message, self.partial_text),
        )


class UnknownOpenCodeError(OpenCodeError):
    """Unclassified opencode CLI error."""

    def __init__(
        self,
        node_id: str,
        exit_code: int = -1,
        raw_message: str = "",
        stderr: str = "",
    ):
        self.stderr = stderr
        super().__init__(node_id, "unknown", exit_code, raw_message)

    def __reduce__(self):
        return (
            self.__class__,
            (self.node_id, self.exit_code, self.raw_message, self.stderr),
        )


class ExportError(OpenCodeError):
    """The agent ran and produced a session, but the transcript export failed.

    Deliberately NOT retried by re-running the agent: ``run`` already executed
    (possibly editing files), so a fresh full run would be an at-least-once
    mutation. The caller should treat the attempt as failed; the session id in
    ``raw_message`` allows manual ``opencode export`` forensics.
    """

    def __init__(
        self,
        node_id: str,
        exit_code: int = -1,
        raw_message: str = "",
        session_id: str = "",
    ):
        self.session_id = session_id
        self._base_message = raw_message
        raw = f"{raw_message} (session {session_id})" if session_id else raw_message
        super().__init__(node_id, "export_failed", exit_code, raw)

    def __reduce__(self):
        return (
            self.__class__,
            (self.node_id, self.exit_code, self._base_message, self.session_id),
        )


# ---------------------------------------------------------------------------
# Session-id parser
# ---------------------------------------------------------------------------

_SESSION_ID_RE = re.compile(r"\bses_[A-Za-z0-9]+\b")


def parse_session_id(stdout: str) -> Optional[str]:
    """Pull the opencode session id out of ``run --format json`` stdout.

    Each event is ``{type, sessionID, part:{sessionID, ...}}``; the opening
    ``step_start`` line reliably carries it. Falls back to a regex scan if the
    JSON shape changes.
    """
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        sid = event.get("sessionID") or (event.get("part") or {}).get("sessionID")
        if sid:
            return sid
    m = _SESSION_ID_RE.search(stdout)
    return m.group(0) if m else None


def parse_run_error(stdout: str) -> Optional[dict]:
    """Pull the first structured error out of ``run --format json`` stdout.

    opencode emits ``{"type":"error", "sessionID":..., "error":{name, data}}``
    events for failures that happen before/around the model request — notably an
    unknown model id, which surfaces as ``{"name":"UnknownError","data":{"message":
    "Model not found: ..."}}``. These never reach the session export's
    ``messages[].info.error`` because no assistant message is ever created, so
    the run stream is the *only* place they appear (confirmed against opencode
    1.15.13). Returns the first such ``error`` dict (``{name, data}``), or
    ``None``. Genuine provider errors (e.g. APIError 401) appear in *both* the run
    stream and the export; the export copy is richer (full ``responseHeaders``),
    so callers prefer it and use this only as a fallback.
    """
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "error":
            err = event.get("error")
            if isinstance(err, dict) and "name" in err:
                return err
    return None


# ---------------------------------------------------------------------------
# Custom model providers
# ---------------------------------------------------------------------------


@dataclass
class AdditionalModelProvider:
    """A custom model provider to inject into the opencode config's ``provider`` block.

    opencode is provider-agnostic: beyond its built-in providers you can declare a
    custom or self-hosted one — an OpenAI-compatible endpoint, a private gateway, a
    local vLLM/Ollama server, etc. — directly in the config under ``provider.<id>``.
    Each entry names the AI-SDK loader package (``npm``), a display ``name``, the SDK
    ``options`` (notably ``base_url`` / ``api_key``), and the ``models`` the provider
    serves. See https://opencode.ai/docs/providers (Custom providers) for the schema.

    Once declared, select one of its models by passing ``model="<id>/<model-id>"`` to
    :class:`OpenCodeLLM` — e.g. ``AdditionalModelProvider(id="my-vllm", ...)`` exposes
    its models as ``my-vllm/<model-id>``.

    Attributes:
        id: Provider key. Used both as the key under ``provider`` in the config and
            as the ``provider`` half of ``provider/model``. Must be unique.
        models: Either a list of model-id strings (each expands to a bare ``{}``
            entry) or a dict mapping model-id -> model config, e.g.
            ``{"name": ..., "limit": {...}, "cost": {...}, "options": {...}}``.
        npm: The AI-SDK package opencode loads to talk to this provider. Defaults to
            ``@ai-sdk/openai-compatible``, which fits any OpenAI-compatible endpoint.
        name: Human-readable display name (defaults to ``id`` when omitted).
        base_url: Endpoint URL; written to ``options.baseURL``. Optional if supplied
            via ``options`` instead.
        api_key: Credential; written to ``options.apiKey``. May be a literal secret
            or an opencode ``{env:NAME}`` template that opencode expands at runtime
            (preferred — keeps the secret out of the on-disk config file).
        options: Extra SDK options merged into the provider's ``options`` block
            (e.g. ``headers``, custom timeouts). On conflict these win over
            ``base_url`` / ``api_key``.
    """

    id: str
    models: Union[List[str], Dict[str, dict]]
    npm: str = "@ai-sdk/openai-compatible"
    name: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    options: Optional[Dict[str, object]] = None

    def to_config_entry(self) -> dict:
        """Render this provider as an opencode ``provider.<id>`` config value."""
        options: dict = {}
        if self.base_url is not None:
            options["baseURL"] = self.base_url
        if self.api_key is not None:
            options["apiKey"] = self.api_key
        if self.options:
            options.update(self.options)

        # A list of ids -> bare ``{id: {}}`` entries; a dict is passed through.
        if isinstance(self.models, dict):
            models = dict(self.models)
        else:
            models = {model_id: {} for model_id in self.models}

        entry: dict = {"npm": self.npm, "name": self.name or self.id, "models": models}
        if options:
            entry["options"] = options
        return entry


class OpenCodeLLM(LLMCallBase):
    """Wraps the ``opencode`` CLI as an LLM backend.

    Each :meth:`prompt` call runs ``opencode run`` (to create a session and get
    its id) then ``opencode export`` (to read the assistant response + usage
    from opencode's local DB). Returns the same :class:`QueryResult` shape as the
    other backends; ``returncode`` is the ``run`` exit code.
    """

    # Honors both --dangerously-skip-permissions and a `permission` config block.
    supports_dangerously_skip_permissions = True
    supports_config = True

    def __init__(
        self,
        model: Optional[str] = None,
        system_message: str = "",
        timeout_seconds: int = 600,
        retries: int = 3,
        logging_name: str = "opencode",
        logging_level: int = logging.DEBUG,
        log_dir: Optional[str] = None,
        opencode_bin: str = "opencode",
        agent_name: str = "chia",
        work_dir: Optional[str] = None,
        extra_cli_args: Optional[List[str]] = None,
        additional_providers: Optional[List[AdditionalModelProvider]] = None,
        provider_options: Optional[dict] = None,
        dangerously_skip_permissions: bool = True,
        config: Optional[dict] = None,
        export_timeout_seconds: int = 180,
        export_retries: int = 2,
    ):
        super().__init__(system_message=system_message,
                         dangerously_skip_permissions=dangerously_skip_permissions,
                         config=config)
        self.logging_level = logging_level
        self.logging_name = logging_name
        self.retries = retries
        self.timeout_seconds = timeout_seconds
        self.export_timeout_seconds = export_timeout_seconds
        self.export_retries = export_retries
        self.model = model
        self.opencode_bin = opencode_bin
        self.agent_name = agent_name
        self.work_dir = work_dir
        self.extra_cli_args = extra_cli_args or []
        self.additional_providers = additional_providers or []
        # provider id -> option dict (e.g. timeout/chunkTimeout in ms)
        self.provider_options = provider_options or {}
        self.logger = logging.getLogger(logging_name)
        self._last_metadata: dict = {}
        self._last_export_error: Optional[dict] = None

        self.logger.warning(
            "OpenCodeLLM is experimental: only exercised by unit tests so far, "
            "not validated in production."
        )

        # opencode falls back to its own configured default model when none is
        # passed on the CLI, so model is optional here — just say so.
        if self.model is None:
            self.logger.info(
                "OpenCodeLLM: no model specified; opencode will use its "
                "configured default model."
            )

        self._log_dir = log_dir
        if log_dir is not None:
            os.makedirs(log_dir, exist_ok=True)
            run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
            self._log_prefix = os.path.join(log_dir, f"{logging_name}_{run_id}")
        else:
            self._log_prefix = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @ChiaFunction(resources={"opencode_creds": 0.01})
    def prompt(
        self,
        user_message: str,
        tools: Optional[List[ChiaTool]] = [],
    ) -> QueryResult:
        """Send *user_message* to opencode and return the response.

        Returns:
            :class:`QueryResult` with ``success=True`` when opencode ran cleanly,
            or ``success=False`` when every retry attempt failed.

        Raises:
            RateLimitError / AuthenticationError / BillingError /
            InvalidRequestError: propagate immediately.
            ServerError: after all retries with exponential backoff.
            MaxOutputTokensError: after one retry attempt.
        """
        from chia.trace.profiler import get_profiler

        profiler = get_profiler()

        reason = ""
        for attempt in range(self.retries):
            try:
                self._last_metadata = {}
                self._last_export_error = None
                cli = self._run_opencode(user_message, tools)
                self._last_metadata["model"] = self.model or "<opencode default>"
                self._last_metadata["tools"] = [
                    {"name": t.name, "hostname": getattr(t, "hostname", None),
                     "port": getattr(t, "port", None),
                     "node_id": getattr(t, "node_id", None)}
                    for t in tools
                ]
                if profiler.enabled and self._last_metadata:
                    profiler.add_info(self._last_metadata)

                self._classify_error(
                    cli, export_error=getattr(self, "_last_export_error", None),
                )

                cli.success = True
                return cli

            # -- Never retry: propagate immediately --
            except (RateLimitError, AuthenticationError, BillingError, InvalidRequestError):
                raise

            # -- The agent ran; never re-run it just because the export failed --
            except ExportError as exc:
                self.logger.warning(
                    "Export failed after successful run (not re-running): %s", exc,
                )
                self._last_metadata["failure_reason"] = "export_failed"
                return QueryResult(result="", returncode=exc.exit_code,
                                   stderr=str(exc), stream_result="", success=False)

            # -- Retry once: stochastic generation may produce shorter output --
            except MaxOutputTokensError:
                reason = "max_output_tokens"
                self._last_metadata["failure_reason"] = reason
                if attempt == 0:
                    self.logger.warning(
                        "Max output tokens on attempt %d/%d, retrying once",
                        attempt + 1, self.retries,
                    )
                    continue
                raise

            # -- Retry with exponential backoff: transient service issue --
            except ServerError as exc:
                reason = f"server_error: {exc.raw_message[:120]}"
                self._last_metadata["failure_reason"] = reason
                backoff = min(5 * 2 ** attempt, 60)
                self.logger.warning(
                    "Server error on attempt %d/%d, backing off %ds",
                    attempt + 1, self.retries, backoff,
                )
                _time.sleep(backoff)

            except UnknownOpenCodeError as exc:
                reason = f"unknown: {exc.raw_message[:200]}"
                self._last_metadata["failure_reason"] = reason
                self.logger.warning(
                    "Unknown error on attempt %d/%d: %s",
                    attempt + 1, self.retries, exc,
                )
                if attempt + 1 < self.retries:
                    _time.sleep(min(5 * 2 ** attempt, 30))

            except subprocess.TimeoutExpired:
                reason = f"timeout after {self.timeout_seconds}s"
                self._last_metadata["failure_reason"] = reason
                self.logger.warning(
                    "Timeout on attempt %d/%d", attempt + 1, self.retries,
                )

            except Exception as exc:
                reason = f"unexpected: {exc}"
                self._last_metadata["failure_reason"] = reason
                self.logger.warning(
                    "Unexpected error on attempt %d/%d: %s",
                    attempt + 1, self.retries, exc,
                )
            finally:
                self._record_usage(attempt + 1)
        return QueryResult(result="", returncode=-1,
                           stderr=f"opencode call failed: {reason}",
                           stream_result="", success=False)

    def _record_usage(self, attempt: int) -> None:
        """Best-effort per-attempt usage line (never affects the call)."""
        if self._log_prefix is None:
            return
        try:
            record = {
                "ts": datetime.now().isoformat(timespec="seconds"),
                "attempt": attempt,
                "model": self.model,
                **{k: v for k, v in self._last_metadata.items()
                   if k not in ("tools",)},
            }
            with open(f"{self._log_prefix}.usage.jsonl", "a") as handle:
                handle.write(json.dumps(record, default=str) + "\n")
        except OSError:
            pass

    def _get_node_id(self) -> str:
        try:
            return ray.get_runtime_context().get_node_id()
        except Exception:
            return "unknown"

    def _classify_error(self, cli: QueryResult,
                        export_error: Optional[dict] = None) -> None:
        """Inspect *cli* and *export_error* and raise a typed error if wrong.

        ``opencode run`` almost always exits 0 even on failure (opencode bug
        #14551), so the exit code alone is not trustworthy. Logic:

        1. Clean run (exit 0, non-empty result, no structured error) -> return.
        2. Structured ``export_error`` (a ``{name, data}`` object from the
           session export or run stream) -> map to a typed error. This is the
           only reliable signal and the only thing we classify on.
        3. Any other failure (no structured error: a CLI/process-level failure
           on stderr, or an empty response) -> :class:`UnknownOpenCodeError`
           with the raw stderr attached. We deliberately do NOT keyword-match
           stderr: opencode emits its real errors as structured JSON (handled by
           (2)), so stderr only carries CLI/usage text, and guessing a type from
           it was imprecise — better to surface it honestly as unknown.

        Note the guard requires ``not export_error``: a structured error is
        honored even on an exit-0 run that returned partial text.
        """
        if cli.returncode == 0 and cli.result and not export_error:
            return

        node_id = self._get_node_id()

        # -- Path A: structured error from the session export (preferred) --
        if export_error:
            name = export_error.get("name", "")
            data = export_error.get("data", {}) or {}
            message = data.get("message", "") or ""
            status = data.get("statusCode")

            # Rate limit — honor the provider's Retry-After when present.
            if status == 429:
                headers = data.get("responseHeaders", {}) or {}
                retry_after = headers.get("retry-after") or headers.get("Retry-After")
                reset_time = datetime.now(timezone.utc) + timedelta(seconds=60)
                if retry_after:
                    try:
                        reset_time = datetime.now(timezone.utc) + timedelta(
                            seconds=int(retry_after),
                        )
                    except (ValueError, TypeError):
                        pass
                raise RateLimitError(
                    node_id=node_id,
                    reset_time=reset_time,
                    raw_message=message,
                    exit_code=cli.returncode,
                )

            # Authentication.
            if name == "ProviderAuthError" or status in (401, 403):
                raise AuthenticationError(node_id, cli.returncode, message)

            # Billing / quota — APIError whose message names a billing problem.
            if name == "APIError" and message:
                if any(kw in message.lower() for kw in (
                    "billing", "quota", "payment", "credit", "subscription", "plan",
                )):
                    raise BillingError(node_id, cli.returncode, message)

            # Output token limit / context overflow.
            if name in ("ContextOverflowError", "MessageOutputLengthError"):
                raise MaxOutputTokensError(
                    node_id, cli.returncode, message, partial_text=cli.result,
                )

            # Server error (5xx or explicitly retryable) vs. invalid request.
            if name == "APIError":
                if (status and status >= 500) or data.get("isRetryable"):
                    raise ServerError(
                        node_id, exit_code=cli.returncode, raw_message=message,
                    )
                raise InvalidRequestError(node_id, cli.returncode, message)

            # Any other structured error (MessageAbortedError, UnknownError, ...).
            raise UnknownOpenCodeError(
                node_id, cli.returncode, message or str(export_error),
                stderr=cli.stderr,
            )

        # No structured error: a CLI/process-level failure (its message is on
        # stderr) or an empty response. opencode surfaces its real errors as
        # structured JSON (handled above), so there's nothing reliable to
        # classify here — report it honestly as unknown with the stderr attached.
        raise UnknownOpenCodeError(
            node_id, cli.returncode, cli.stderr[:300] or "empty response",
            stderr=cli.stderr,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _build_config(self, tools: List[ChiaTool]) -> dict:
        """Build the opencode config (written to OPENCODE_CONFIG).

        Defines the ``chia`` agent carrying our system prompt, one remote MCP
        server per ChiaTool, and any custom model providers passed at construction.
        """
        cfg: dict = {
            "$schema": "https://opencode.ai/config.json",
            "agent": {
                self.agent_name: {
                    "mode": "primary",
                    "prompt": self.system_message or "You are a helpful assistant.",
                }
            },
        }
        if tools:
            mcp: dict = {}
            for tool in tools:
                port = getattr(tool, "port", 8000)
                mcp[tool.name] = {
                    "type": "remote",
                    "url": f"http://{tool.hostname}:{port}/{tool.name}/mcp",
                    "enabled": True,
                }
            cfg["mcp"] = mcp

        # Config block. Defaults to allowing all tools — notably
        # external_directory, whose "ask" default blocks a non-interactive run
        # (the --dangerously-skip-permissions flag does NOT cover it).
        # Override via the `permission` kwarg.
        cfg["permission"] = self.config if self.config is not None else {
            "edit": "allow",
            "bash": "allow",
            "webfetch": "allow",
            "external_directory": "allow",
        }
        if self.provider_options:
            provider_cfg: dict = cfg.setdefault("provider", {})
            for provider_id, entry in self.provider_options.items():
                target = provider_cfg.setdefault(provider_id, {})
                for key, value in entry.items():
                    if isinstance(value, dict):
                        target.setdefault(key, {}).update(value)
                    else:
                        target[key] = value
        if self.additional_providers:
            provider_cfg: dict = cfg.setdefault("provider", {})
            for provider in self.additional_providers:
                provider_cfg[provider.id] = provider.to_config_entry()
        return cfg

    def _build_run_cmd(self, user_message: str) -> list:
        """Build the ``opencode run`` command list (message is a positional arg)."""
        cmd = [
            self.opencode_bin,
            "run",
            "--format", "json",
            "--agent", self.agent_name,
        ]
        if self.dangerously_skip_permissions:
            cmd.append("--dangerously-skip-permissions")
        if self.model:  # omit --model so opencode uses its configured default
            cmd += ["--model", self.model]
        if self.work_dir:
            cmd += ["--dir", self.work_dir]
        if self.extra_cli_args:
            cmd += self.extra_cli_args
        cmd.append(user_message)
        return cmd

    def _run_opencode(
        self,
        user_message: str,
        tools: Optional[List[ChiaTool]] = None,
    ) -> QueryResult:
        """Run ``opencode run`` then ``opencode export`` and assemble a QueryResult."""
        tools = tools or []
        cfg = self._build_config(tools)

        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", prefix="opencode_cfg_", delete=False
        )
        json.dump(cfg, tmp)
        tmp.close()
        cfg_path = tmp.name

        # opencode picks up our config via OPENCODE_CONFIG; disable project
        # config so a stray opencode.json in cwd can't shadow it. Stored
        # credentials / provider env vars in the inherited environment provide
        # auth (we don't touch them).
        env = dict(os.environ)
        env["OPENCODE_CONFIG"] = cfg_path
        env["OPENCODE_DISABLE_PROJECT_CONFIG"] = "1"

        run_cmd = self._build_run_cmd(user_message)
        self.logger.info("Running: %s ...", " ".join(run_cmd[:6]))

        try:
            # Capture via a file, not a pipe: a large run stream would otherwise
            # be truncated at 64 KiB (see _capture / module docstring), which can
            # drop the trailing error events parse_run_error looks for.
            run = self._capture(run_cmd, env)
        finally:
            try:
                os.unlink(cfg_path)
            except OSError:
                pass

        session_id = parse_session_id(run.stdout)
        self._last_metadata["session_id"] = session_id
        # Errors that happen before an assistant message exists (e.g. unknown
        # model) only appear as `type:"error"` events in the run stream, never
        # in the export — capture them here so they can be classified too.
        run_error = parse_run_error(run.stdout)

        # A failed run (non-zero, or no session created) → return so the caller
        # classifies. Surface any run-stream error so it isn't lost. Don't
        # attempt an export without a session id.
        if run.returncode != 0 or session_id is None:
            if run.returncode != 0:
                self.logger.warning(
                    "opencode run exited %d: %s", run.returncode, run.stderr[:500]
                )
            self._last_export_error = run_error
            self._last_metadata["failure_reason"] = "run_failed"
            return QueryResult(
                result="",
                returncode=run.returncode if run.returncode != 0 else -1,
                stderr=run.stderr or "no session id in opencode output",
                stream_result=run.stdout,
            )

        try:
            export = self._run_export(session_id, env)
            final_text, meta, stream, export_error = self._extract_from_export(export)
        except ExportError:
            raise
        except Exception as exc:
            # Once the session exists, ANY downstream failure must not trigger
            # a re-run: the agent may already have mutated the workspace.
            raise ExportError(
                node_id=self._get_node_id(), exit_code=0,
                raw_message=f"post-run export/extraction failed: {exc}",
                session_id=session_id,
            ) from exc
        meta["session_id"] = session_id
        self._last_metadata = meta
        # Prefer the export's error (richer — full responseHeaders); fall back to
        # the run-stream error for pre-request failures the export never records.
        self._last_export_error = export_error or run_error

        if self._log_prefix is not None:
            # Best-effort only: prompt() may run on a remote worker whose
            # filesystem lacks the (driver-side) log_dir — a logging hiccup must
            # never fail an otherwise-successful call. The transcript is always
            # returned in stream_result regardless.
            try:
                os.makedirs(os.path.dirname(self._log_prefix), exist_ok=True)
                truncated = user_message[:500] + ("..." if len(user_message) > 500 else "")
                with open(f"{self._log_prefix}.log", "a") as f:
                    f.write("=" * 80 + "\n")
                    f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] session {session_id}\n")
                    f.write("=" * 80 + "\n\n")
                    f.write(f"[User Message]\n{truncated}\n\n")
                    f.write(stream)
                    f.write("-" * 80 + "\n\n")
            except OSError as exc:
                self.logger.warning(
                    "Could not write opencode log %s.log: %s", self._log_prefix, exc
                )

        return QueryResult(
            result=final_text,
            returncode=0,
            stderr=run.stderr,
            stream_result=stream,
        )

    def _capture(self, cmd: list, env: dict,
                 timeout: Optional[int] = None) -> SimpleNamespace:
        """Run *cmd* capturing stdout to a temp FILE and return it.

        Returns a ``SimpleNamespace(returncode, stdout, stderr)`` (the same shape
        ``subprocess.run`` would, so callers read ``.stdout`` etc. unchanged).

        Why a file instead of ``capture_output=True``: opencode truncates its
        stdout at the OS pipe buffer (64 KiB on Linux) and still exits 0 when
        stdout is a pipe, so large ``run`` streams / ``export`` payloads come back
        cut mid-JSON and unparseable. A regular file has no such limit. stderr is
        small, so it stays on a pipe. ``stdin=DEVNULL`` because ``run`` blocks on
        an open stdin pipe. ``subprocess.TimeoutExpired`` propagates to the caller.

        The child starts in its own session (``start_new_session=True``), so on
        timeout the WHOLE process group is killed — opencode spawns tool
        subprocesses (shells, etc.) that ``subprocess.run``'s direct-child kill
        would leave behind, mutating the workspace after the deadline.
        """
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".out", prefix="opencode_out_", delete=False
        )
        out_path = tmp.name
        tmp.close()
        effective_timeout = self.timeout_seconds if timeout is None else timeout
        try:
            with open(out_path, "w") as out_fh:
                proc = subprocess.Popen(
                    cmd,
                    stdin=subprocess.DEVNULL,
                    stdout=out_fh,
                    stderr=subprocess.PIPE,
                    text=True,
                    env=env,
                    start_new_session=True,
                )
                try:
                    _, stderr = proc.communicate(timeout=effective_timeout)
                except subprocess.TimeoutExpired:
                    self._kill_process_group(proc)
                    raise
            with open(out_path, "r") as in_fh:
                stdout = in_fh.read()
            return SimpleNamespace(
                returncode=proc.returncode, stdout=stdout, stderr=stderr or ""
            )
        finally:
            try:
                os.unlink(out_path)
            except OSError:
                pass

    @staticmethod
    def _kill_process_group(proc: subprocess.Popen) -> None:
        """SIGKILL the child's whole process group, then reap it."""
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                proc.kill()
            except OSError:
                pass
        try:
            proc.wait(timeout=10)
        except (subprocess.TimeoutExpired, OSError):
            pass

    def _run_export(self, session_id: str, env: dict) -> dict:
        """``opencode export <id>`` → parsed session JSON.

        Retried up to ``export_retries`` total attempts with a short backoff:
        an export failure is transient (DB read/parse), and re-running the
        whole agent because an export hiccuped would be an at-least-once
        mutation of the workspace. Raises :class:`ExportError` when exhausted.
        """
        cmd = [self.opencode_bin, "export", session_id]
        last_error = "export failed"
        for attempt in range(max(1, self.export_retries)):
            try:
                proc = self._capture(cmd, env,
                                     timeout=self.export_timeout_seconds)
            except subprocess.TimeoutExpired:
                last_error = (f"opencode export timed out after "
                              f"{self.export_timeout_seconds}s")
                self.logger.warning("%s for %s (attempt %d/%d)", last_error,
                                    session_id, attempt + 1,
                                    self.export_retries)
                _time.sleep(min(2 * (attempt + 1), 10))
                continue
            if proc.returncode != 0:
                last_error = (f"opencode export exited {proc.returncode}: "
                              f"{(proc.stderr or '')[:200]}")
                self.logger.warning("%s for %s (attempt %d/%d)", last_error,
                                    session_id, attempt + 1,
                                    self.export_retries)
                _time.sleep(min(2 * (attempt + 1), 10))
                continue
            try:
                return json.loads(proc.stdout)
            except json.JSONDecodeError:
                last_error = "opencode export returned non-JSON"
                self.logger.warning("%s for %s (attempt %d/%d)", last_error,
                                    session_id, attempt + 1,
                                    self.export_retries)
                continue
        raise ExportError(
            node_id=self._get_node_id(), exit_code=-1,
            raw_message=last_error, session_id=session_id,
        )

    def _extract_from_export(self, export: dict):
        """Pull final assistant text, usage metadata, a stream trace, and any error.

        Export shape::

            {info, messages: [{info:{role, tokens, cost, error}, parts: [...]}]}

        Parts: ``{type:"text", text}``, ``{type:"reasoning", text}``,
        ``{type:"tool", tool, state:{status, input, output}}``, plus
        ``step-start``/``step-finish``. The final answer is the text of the last
        assistant message; tokens/cost are summed across assistant messages.

        Returns:
            ``(text, metadata, stream, export_error)`` where *export_error* is the
            ``{name, data}`` dict from the first assistant message carrying an
            ``info.error`` (opencode's discriminated error object), or ``None``.
            This matters because ``opencode run`` almost always exits 0 even on
            failure (opencode bug #14551), so the exit code alone can't be trusted
            — the structured error in the export is the reliable signal.
        """
        stream_parts: list[str] = []
        meta = {"input_tokens": 0, "output_tokens": 0, "reasoning_tokens": 0,
                "cache_read": 0, "cache_write": 0, "cost_usd": 0.0, "num_turns": 0}
        last_assistant_text = ""
        export_error = None

        for msg in export.get("messages", []) or []:
            info = msg.get("info", {}) if isinstance(msg, dict) else {}
            role = info.get("role")
            parts = msg.get("parts", []) if isinstance(msg, dict) else []

            if role == "assistant":
                if export_error is None:
                    err = info.get("error")
                    if isinstance(err, dict) and "name" in err:
                        export_error = err

                meta["num_turns"] += 1
                try:
                    tok = info.get("tokens") or {}
                    if isinstance(tok, dict):
                        meta["input_tokens"] += tok.get("input", 0) or 0
                        meta["output_tokens"] += tok.get("output", 0) or 0
                        meta["reasoning_tokens"] += tok.get("reasoning", 0) or 0
                        cache = tok.get("cache") or {}
                        if isinstance(cache, dict):
                            meta["cache_read"] += cache.get("read", 0) or 0
                            meta["cache_write"] += cache.get("write", 0) or 0
                    meta["cost_usd"] += info.get("cost", 0) or 0
                except (TypeError, ValueError):
                    pass  # malformed usage metadata must never mask the response

                turn_text: list[str] = []
                for p in parts:
                    if not isinstance(p, dict):
                        continue
                    ptype = p.get("type")
                    if ptype == "text":
                        txt = p.get("text", "")
                        turn_text.append(txt)
                        stream_parts.append(f"[Response]\n{txt}\n\n")
                    elif ptype == "reasoning":
                        stream_parts.append(f"[Thinking]\n{p.get('text', '')}\n\n")
                    elif ptype == "tool":
                        state = p.get("state") or {}
                        args = json.dumps(state.get("input", {}))
                        if len(args) > 2000:
                            args = args[:2000] + "\n... [truncated]"
                        stream_parts.append(
                            f"[Tool Call: {p.get('tool', 'unknown')}]\nArgs: {args}\n\n"
                        )
                        out = state.get("output", "")
                        if not isinstance(out, str):
                            out = json.dumps(out)
                        if len(out) > 2000:
                            out = out[:2000] + "\n... [truncated]"
                        if out:
                            stream_parts.append(f"[Tool Result]\n{out}\n\n")
                if turn_text:
                    last_assistant_text = "".join(turn_text)

        meta = {k: v for k, v in meta.items() if v}
        return last_assistant_text, meta, "".join(stream_parts), export_error
