"""Offline tests for the provider-neutral PEWeaver model shim.

Every backend below is an in-process fake.  This suite deliberately has no
credentials, network, Ray, or model dependency.
"""

from __future__ import annotations

import json
import hashlib
import os
import tempfile
import threading
import time
import unittest
import urllib.error
from unittest import mock
from pathlib import Path

from .model_shim import (ModelRequest, ModelRoute, ProviderNeutralModelShim,
                         ShimConfig, _StdlibGeminiBackend,
                         _StdlibOpenRouterBackend, _SubprocessOpenCodeBackend)
from .model_neutral_loop import ModelNeutralCampaign


class RateLimitError(Exception):
    pass


class BillingError(Exception):
    pass


class ServerError(Exception):
    pass


class AuthenticationError(Exception):
    pass


class AmbiguousCompletion(Exception):
    pass


def req(role="lead", **kwargs):
    return ModelRequest.create(run_id="run", work_id="work", request_id=kwargs.pop("request_id", None),
                               role=role, prompt=kwargs.pop("prompt", "bounded prompt"),
                               context_hash="context", token_cap=kwargs.pop("token_cap", 100), **kwargs)


class FakeBackend:
    def __init__(self, route, action):
        self.route = route
        self.action = action
        self.calls = 0

    def prompt(self, _prompt):
        self.calls += 1
        value = self.action(self.route, self.calls)
        if isinstance(value, BaseException):
            raise value
        return value


class ModelShimOfflineTests(unittest.TestCase):
    def make(self, action, **config):
        backends = {}
        def factory(route):
            backends[route.provider] = FakeBackend(route, action)
            return backends[route.provider]
        return ProviderNeutralModelShim(ShimConfig(**config), backend_factory=factory), backends

    def test_success_idempotency_and_hash(self):
        shim, backends = self.make(lambda *_: {"success": True, "output": "answer",
                                               "usage": {"total_tokens": 3, "cost_usd": .1}})
        request = req(request_id="same")
        first = shim.call(request)
        second = shim.call(request)
        self.assertTrue(first.success)
        self.assertEqual(first.output_hash, second.output_hash)
        self.assertEqual(backends["opencode"].calls, 1)

    def test_rate_quota_fails_over_only_when_two_gates_are_set(self):
        action = lambda route, _: RateLimitError("secret=do-not-log") if route.provider == "opencode" else {
            "success": True, "output": "ok"}
        shim, backends = self.make(action, openrouter_cli_opt_in=True, openrouter_runtime_opt_in=True)
        # The environment gate is intentionally absent, so no paid route runs.
        result = shim.call(req())
        self.assertEqual(result.status, "rate_or_quota")
        self.assertNotIn("openrouter", backends)

    def test_rate_quota_and_billing_fallback(self):
        for failure in (RateLimitError("429"), BillingError("402")):
            def action(route, _calls, failure=failure):
                return failure if route.provider == "opencode" else {"success": True, "output": "ok"}
            shim, backends = self.make(action, openrouter_cli_opt_in=True, openrouter_runtime_opt_in=True)
            with mock.patch.dict("os.environ", {"PEWEAVER_ALLOW_OPENROUTER_BILLABLE": "1"}):
                result = shim.call(req(request_id="r-" + type(failure).__name__))
            self.assertTrue(result.success)
            self.assertEqual(result.provider, "openrouter")
            self.assertIn("openrouter", backends)

    def test_repeated_server_error_retries_then_falls_back(self):
        def action(route, calls):
            if route.provider == "opencode":
                return ServerError("503")
            return {"success": True, "output": "fallback"}
        shim, backends = self.make(action, openrouter_cli_opt_in=True, openrouter_runtime_opt_in=True,
                                    transient_attempts=2)
        with mock.patch.dict("os.environ", {"PEWEAVER_ALLOW_OPENROUTER_BILLABLE": "1"}):
            result = shim.call(req(request_id="server"))
        self.assertTrue(result.success)
        self.assertEqual(backends["opencode"].calls, 2)

    def test_auth_failure_never_falls_back(self):
        shim, backends = self.make(lambda *_: AuthenticationError("bad auth"),
                                    openrouter_cli_opt_in=True, openrouter_runtime_opt_in=True)
        with mock.patch.dict("os.environ", {"PEWEAVER_ALLOW_OPENROUTER_BILLABLE": "1"}):
            result = shim.call(req(request_id="auth"))
        self.assertEqual(result.status, "authentication")
        self.assertNotIn("openrouter", backends)

    def test_stall_can_be_cancelled_without_fallback(self):
        state = {"finished": False}
        def action(*_):
            time.sleep(2)
            state["finished"] = True
            return {"success": True, "output": "late"}
        shim, backends = self.make(action, openrouter_cli_opt_in=True, openrouter_runtime_opt_in=True,
                                    default_deadline_seconds=10)
        request = req(request_id="stall", deadline=time.time() + 10)
        box = []
        thread = threading.Thread(target=lambda: box.append(shim.call(request)))
        thread.start()
        time.sleep(.03)
        shim.cancel("stall")
        thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(box[0].status, "ambiguous_completion")
        self.assertFalse(state["finished"], "uncancellable backend must remain unresolved")
        self.assertNotIn("openrouter", backends)

    def test_ambiguous_completion_stops(self):
        shim, backends = self.make(lambda *_: AmbiguousCompletion("possibly committed"),
                                    openrouter_cli_opt_in=True, openrouter_runtime_opt_in=True)
        with mock.patch.dict("os.environ", {"PEWEAVER_ALLOW_OPENROUTER_BILLABLE": "1"}):
            result = shim.call(req(request_id="ambiguous"))
        self.assertEqual(result.status, "ambiguous_completion")
        self.assertNotIn("openrouter", backends)

    def test_candidate_mutation_blocks_fallback(self):
        state = ["original"]
        def action(route, _calls):
            state[0] = "changed"
            return RateLimitError("429")
        shim, backends = self.make(action, openrouter_cli_opt_in=True, openrouter_runtime_opt_in=True)
        request = req(request_id="mutation", candidate_hash="original",
                      candidate_hash_reader=lambda: state[0])
        with mock.patch.dict("os.environ", {"PEWEAVER_ALLOW_OPENROUTER_BILLABLE": "1"}):
            result = shim.call(request)
        self.assertEqual(result.status, "candidate_mutation_blocked")
        self.assertNotIn("openrouter", backends)

    def test_budget_exhaustion(self):
        shim, _ = self.make(lambda *_: {"success": True, "output": "ok",
                                         "usage": {"total_tokens": 1, "cost_usd": .1}},
                            max_calls_per_run=1)
        self.assertTrue(shim.call(req(request_id="budget-1")).success)
        self.assertEqual(shim.call(req(request_id="budget-2")).status, "budget_exhausted")

    def test_ledger_redacts_prompt_and_exception_text(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "ledger.jsonl"
            shim, _ = self.make(lambda *_: AuthenticationError("API_KEY=super-secret"),
                                ledger_path=ledger)
            shim.call(req(request_id="redact", prompt="password=super-secret"))
            text = ledger.read_text()
            self.assertNotIn("super-secret", text)
            self.assertEqual(len(text.splitlines()), 1)
            self.assertEqual(json.loads(text)["status"], "authentication")

    def test_probe_is_non_network_and_default_openrouter_off(self):
        shim, _ = self.make(lambda *_: {"success": True, "output": "unused"})
        result = shim.probe()
        self.assertFalse(result["attempted"])
        self.assertFalse(result["openrouter_enabled"])

    def test_model_neutral_campaign_requires_explicit_evaluator_acceptance(self):
        shim, _ = self.make(lambda *_: {"success": True, "output": "candidate"})
        state = ["0" * 64]
        def stage(_output):
            state[0] = "1" * 64
            return state[0]
        campaign = ModelNeutralCampaign(shim, max_turns=1)
        result = campaign.run(
            run_id="campaign", work_id="work", context_hash="context",
            candidate_hash="0" * 64, lead_prompt="rank", worker_prompt="patch",
            candidate_hash_reader=lambda: state[0], stage_candidate=stage,
            evaluate_candidate=lambda _hash: {"passed": True, "candidate_accepted": False},
        )
        self.assertEqual(result.status, "exhausted")
        self.assertFalse(result.candidate_accepted)

    def test_campaign_hands_bounded_sol_plan_and_feedback_to_repairs(self):
        prompts = []
        def action(route, _calls):
            def run(prompt, **_kwargs):
                prompts.append(prompt)
                return {"success": True, "output": "SOL PLAN: isolate stage 3" if "gpt-5.6-sol" in route.model else "candidate"}
            return run
        # A callable backend is used because this test also records the exact
        # prompt passed to each worker turn.
        class Capture:
            def __init__(self, route): self.route = route
            def prompt(self, prompt, **kwargs):
                prompts.append(prompt)
                return {"success": True, "output": "SOL PLAN: isolate stage 3" if "gpt-5.6-sol" in self.route.model else "candidate"}
        shim = ProviderNeutralModelShim(ShimConfig(), backend_factory=Capture)
        state = ["0" * 64]
        count = [0]
        def stage(_output):
            count[0] += 1
            state[0] = (str(count[0]) * 64)[:64]
            return state[0]
        eval_count = [0]
        def evaluate(_hash):
            eval_count[0] += 1
            return {"passed": eval_count[0] > 1, "candidate_accepted": eval_count[0] > 1,
                    "status": "failed" if eval_count[0] == 1 else "passed",
                    "mismatch": "latency mismatch"}
        result = ModelNeutralCampaign(shim, max_turns=2, lead_plan_max_chars=24,
                                      feedback_max_chars=80).run(
            run_id="plan", work_id="work", context_hash="context", candidate_hash="0" * 64,
            lead_prompt="rank", worker_prompt="patch", candidate_hash_reader=lambda: state[0],
            stage_candidate=stage, evaluate_candidate=evaluate)
        self.assertEqual(result.status, "accepted")
        self.assertIn("--- SOL ARCHITECTURE PLAN", prompts[1])
        self.assertIn("plan_sha256=" + hashlib.sha256(b"SOL PLAN: isolate stage 3").hexdigest(), prompts[1])
        self.assertIn("latency mi", prompts[2])
        self.assertIn("--- SOL ARCHITECTURE PLAN", prompts[2])

    def test_lead_mutation_is_detected_after_success(self):
        state = ["0" * 64]
        def action(route, _calls):
            if "gpt-5.6-sol" in route.model:
                state[0] = "1" * 64
            return {"success": True, "output": "plan"}
        shim, backends = self.make(action)
        result = ModelNeutralCampaign(shim, max_turns=1).run(
            run_id="lead-mutation", work_id="work", context_hash="context",
            candidate_hash="0" * 64, lead_prompt="rank", worker_prompt="patch",
            candidate_hash_reader=lambda: state[0], stage_candidate=None,
            evaluate_candidate=None)
        self.assertEqual(result.status, "candidate_mutated_by_lead")
        self.assertNotIn("opencode-go/deepseek-v4-flash", [r.route.model for r in backends.values()])

    def test_token_cap_is_passed_to_backend(self):
        seen = []
        class CapBackend:
            def prompt(self, prompt, token_cap=None):
                seen.append(token_cap)
                return {"success": True, "output": "bounded", "usage": {"output_tokens": token_cap}}
        shim = ProviderNeutralModelShim(ShimConfig(), backend_factory=lambda _route: CapBackend())
        result = shim.call(req(request_id="token", token_cap=7))
        self.assertTrue(result.success)
        self.assertEqual(seen, [7])

    def test_openrouter_reservation_blocks_before_paid_call(self):
        calls = []
        def action(route, _calls):
            calls.append(route.provider)
            return RateLimitError("429") if route.provider == "opencode" else {"success": True, "output": "paid"}
        shim, _ = self.make(action, openrouter_cli_opt_in=True, openrouter_runtime_opt_in=True,
                            campaign_cap_usd=.00001, lead_cap_usd=.00001,
                            openrouter_input_rate_usd_per_1k_tokens=0,
                            openrouter_output_rate_usd_per_1k_tokens=1)
        with mock.patch.dict("os.environ", {"PEWEAVER_ALLOW_OPENROUTER_BILLABLE": "1"}):
            result = shim.call(req(request_id="reserve", token_cap=20, estimated_input_tokens=0))
        self.assertEqual(result.status, "budget_exhausted")
        self.assertNotIn("openrouter", calls)

    def test_missing_usage_retains_conservative_reservation(self):
        def action(route, _calls):
            return RateLimitError("429") if route.provider == "opencode" else {"success": True, "output": "paid"}
        shim, _ = self.make(action, openrouter_cli_opt_in=True, openrouter_runtime_opt_in=True,
                            campaign_cap_usd=.00001, lead_cap_usd=.00001,
                            openrouter_input_rate_usd_per_1k_tokens=0,
                            openrouter_output_rate_usd_per_1k_tokens=.001)
        with mock.patch.dict("os.environ", {"PEWEAVER_ALLOW_OPENROUTER_BILLABLE": "1"}):
            self.assertTrue(shim.call(req(request_id="unknown-cost", token_cap=5,
                                         estimated_input_tokens=0)).success)
            self.assertGreater(shim.budget("run").reserved_usd, 0)
            self.assertTrue(shim.call(req(request_id="unknown-cost-2", token_cap=5,
                                         estimated_input_tokens=0)).success)
            self.assertEqual(shim.call(req(request_id="unknown-cost-3", token_cap=5,
                                          estimated_input_tokens=0)).status, "budget_exhausted")

    def test_zero_deadline_uses_one_effective_fixed_deadline(self):
        ticks = iter([100.0] * 10 + [101.0])
        shim, _ = self.make(lambda *_: time.sleep(1), default_deadline_seconds=1)
        shim._clock = lambda: next(ticks, 101.0)
        result = shim.call(req(request_id="effective-deadline", deadline=0))
        self.assertEqual(result.status, "ambiguous_completion")

    def test_opencode_role_permissions_and_variant_command(self):
        with tempfile.TemporaryDirectory() as directory:
            backend = _SubprocessOpenCodeBackend(
                ModelRoute("opencode", "openai/gpt-5.6-sol"), work_dir=Path(directory),
                binary="opencode", timeout_seconds=1, permissions={}, variant="high")
            lead = backend.build_config(17)
            self.assertEqual(lead["permission"]["*"], "deny")
            self.assertEqual(lead["permission"]["read"], "allow")
            self.assertNotIn("edit", lead["permission"])
            self.assertEqual(lead["agent"]["chia"]["options"]["maxOutputTokens"], 17)
            self.assertIn("--variant", backend.build_command("p"))
            backend.set_role("worker")
            self.assertEqual(backend.permission_config()["edit"], "allow")

    def test_opencode_usage_parser_sums_step_finish_records(self):
        stdout = '\n'.join([
            '{"type":"text","part":{"text":"answer"}}',
            '{"type":"step_finish","part":{"tokens":{"input":4,"output":3},"cost":0.12}}',
            '{"type":"step_finish","part":{"tokens":{"input":2,"output":5},"cost":0.08}}',
        ])
        _text, usage = _SubprocessOpenCodeBackend._extract_output_usage(stdout)
        self.assertEqual(_text, "answer")
        self.assertEqual(usage["input_tokens"], 6)
        self.assertEqual(usage["output_tokens"], 8)
        self.assertAlmostEqual(usage["cost_usd"], .2)

    def test_stdlib_openrouter_backend_http_is_mocked_and_bounded(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def read(self):
                return json.dumps({"choices": [{"message": {"content": "answer"}}],
                                   "usage": {"prompt_tokens": 4, "completion_tokens": 2,
                                              "total_tokens": 6, "cost": .01}}).encode()
        seen = []
        def open_url(request, timeout):
            seen.append((request, timeout))
            return Response()
        backend = _StdlibOpenRouterBackend(ModelRoute("openrouter", "deepseek/deepseek-v4-flash"),
                                           timeout_seconds=3)
        with mock.patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-only-key"}), \
                mock.patch("urllib.request.urlopen", side_effect=open_url):
            result = backend.prompt("prompt", token_cap=9)
        self.assertTrue(result["success"])
        self.assertEqual(result["usage"]["output_tokens"], 2)
        self.assertEqual(json.loads(seen[0][0].data)["max_tokens"], 9)
        self.assertEqual(seen[0][1], 3)

    def test_opencode_subprocess_classifies_limit_and_auth_failures(self):
        class Proc:
            pid = 1234
            returncode = 1
            def __init__(self, stderr):
                self._stderr = stderr
            def communicate(self, timeout):
                return ("", self._stderr)
            def poll(self): return 1
        cases = {
            "your credits are exhausted for today": "rate_or_quota",
            "ERROR 429: rate limit exceeded": "rate_or_quota",
            "401 unauthorized: invalid api key": "provider_unavailable",
            "some other failure": "provider_error",
        }
        for stderr, expected in cases.items():
            with tempfile.TemporaryDirectory() as directory, \
                    mock.patch("subprocess.Popen", return_value=Proc(stderr)):
                backend = _SubprocessOpenCodeBackend(
                    ModelRoute("opencode", "opencode-go/deepseek-v4-flash"), work_dir=Path(directory),
                    binary="opencode", timeout_seconds=1, permissions={}, variant="low")
                result = backend.prompt("safe", token_cap=8)
            self.assertEqual(result["error"], expected)

    def test_opencode_subprocess_uses_isolated_xdg_pure_and_model_command(self):
        class Proc:
            pid = 1234
            returncode = 0
            def communicate(self, timeout):
                return ('{"type":"text","part":{"text":"ok"}}\n', "")
            def poll(self): return 0
        seen = {}
        def popen(command, **kwargs):
            seen["command"] = command
            seen["env"] = kwargs["env"]
            return Proc()
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch("subprocess.Popen", side_effect=popen):
            backend = _SubprocessOpenCodeBackend(
                ModelRoute("opencode", "openai/gpt-5.6-sol"), work_dir=Path(directory),
                binary="opencode", timeout_seconds=1, permissions={}, variant="high")
            self.assertTrue(backend.prompt("safe", token_cap=4)["success"])
        self.assertIn("--pure", seen["command"])
        self.assertEqual(seen["command"][seen["command"].index("--model") + 1], "openai/gpt-5.6-sol")
        self.assertEqual(seen["command"][seen["command"].index("--variant") + 1], "high")
        self.assertEqual(seen["env"]["OPENCODE_DISABLE_PROJECT_CONFIG"], "1")
        self.assertTrue(seen["env"]["XDG_CONFIG_HOME"].startswith(directory))

    def test_routes_from_env_overrides_lead_and_worker(self):
        with mock.patch.dict(os.environ, {
                "PEWEAVER_LEAD_ROUTES": "gemini/gemini-3.7-flash,openrouter/openai/gpt-5.6-sol",
                "PEWEAVER_WORKER_ROUTES": "gemini/gemini-3.7-flash,opencode/opencode-go/deepseek-v4-flash"}):
            config = ShimConfig.from_environment()
        self.assertEqual(config.lead_routes[0], ModelRoute("gemini", "gemini-3.7-flash"))
        self.assertEqual(config.lead_routes[1], ModelRoute("openrouter", "openai/gpt-5.6-sol"))
        self.assertEqual(config.worker_routes[1], ModelRoute("opencode", "opencode-go/deepseek-v4-flash"))

    def test_routes_from_env_rejects_unknown_provider(self):
        with mock.patch.dict(os.environ, {"PEWEAVER_LEAD_ROUTES": "skynet/gpt-9"}):
            with self.assertRaises(ValueError):
                ShimConfig.from_environment()

    def test_gemini_route_requires_key_and_fails_over(self):
        class FakeBackend:
            def __init__(self, provider):
                self.provider = provider
            def prompt(self, message, token_cap=4096):
                if self.provider == "gemini":
                    return {"success": False, "error": "provider_unavailable"}
                return {"success": True, "output": "ok", "usage": None}
        seen = []
        def factory(route):
            seen.append(route.provider)
            return FakeBackend(route.provider)
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            shim = ProviderNeutralModelShim(
                ShimConfig(lead_routes=(ModelRoute("gemini", "gemini-3.7-flash"),),
                           worker_routes=(ModelRoute("gemini", "gemini-3.7-flash"),)),
                backend_factory=factory)
            response = shim.call(ModelRequest.create(
                run_id="r1", work_id="w1", role="lead", prompt="p", context_hash="c",
                candidate_hash="h", token_cap=16))
            self.assertEqual(response.status, "blocked")
        shim = ProviderNeutralModelShim(
            ShimConfig(lead_routes=(ModelRoute("gemini", "gemini-3.7-flash"),
                                    ModelRoute("openrouter", "openai/gpt-5.6-sol")),
                       worker_routes=(ModelRoute("gemini", "gemini-3.7-flash"),),
                       openrouter_cli_opt_in=True, openrouter_runtime_opt_in=True),
            backend_factory=factory)
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "k",
                                          "PEWEAVER_ALLOW_OPENROUTER_BILLABLE": "1"}):
            response = shim.call(ModelRequest.create(
                run_id="r2", work_id="w1", role="lead", prompt="p", context_hash="c",
                candidate_hash="h", token_cap=16))
        self.assertTrue(response.success)
        self.assertEqual(response.provider, "openrouter")
        self.assertEqual(seen, ["gemini", "openrouter"])

    def test_stdlib_gemini_backend_parses_and_maps_errors(self):
        backend = _StdlibGeminiBackend(ModelRoute("gemini", "gemini-3.7-flash"), timeout_seconds=1)
        captured = {}
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self):
                return json.dumps({
                    "candidates": [{"content": {"parts": [{"text": "hello"}]}}],
                    "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 2,
                                      "totalTokenCount": 5}}).encode()
        def urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["headers"] = dict(request.header_items())
            return Response()
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}), \
                mock.patch("urllib.request.urlopen", side_effect=urlopen):
            result = backend.prompt("hi", token_cap=32)
        self.assertTrue(result["success"])
        self.assertEqual(result["output"], "hello")
        self.assertEqual(result["usage"]["total_tokens"], 5)
        self.assertEqual(result["usage"]["cost_usd"], 0.0)
        self.assertIn("generateContent", captured["url"])
        self.assertIn("test-key", captured["headers"].get("X-goog-api-key", ""))

        def raise_http_error(request, timeout):
            raise urllib.error.HTTPError(captured["url"], 403, "forbidden", {}, None)
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}), \
                mock.patch("urllib.request.urlopen", side_effect=raise_http_error):
            result = backend.prompt("hi", token_cap=32)
        self.assertEqual(result, {"success": False, "error": "provider_unavailable"})


if __name__ == "__main__":
    unittest.main()
