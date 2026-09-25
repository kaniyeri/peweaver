"""CHIA-dispatch semantics for the shared evaluator nodes (WS1).

Proves that gate dispatch goes through ``.chia_remote()`` when Ray is up,
falls back to direct local calls otherwise, and that infrastructure errors
become RETRY outcomes rather than semantic rejections or acceptances.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import evaluator_nodes as en
from chia_merge import GateOutcome


class FakeNode:
    def __init__(self, result=None, exc=None):
        self.result = result
        self.exc = exc
        self.remote_calls = []
        self.local_calls = []

    def __call__(self, *args, **kwargs):
        self.local_calls.append((args, kwargs))
        if self.exc is not None:
            raise self.exc
        return self.result

    def chia_remote(self, *args, **kwargs):
        self.remote_calls.append((args, kwargs))
        if self.exc is not None:
            raise self.exc
        return ("objectref", self.result)


def _get(ref):
    return ref[1]


def test_dispatch_uses_chia_remote_when_ray_active(monkeypatch):
    monkeypatch.setattr(en, "_ray_active", lambda: True)
    monkeypatch.setattr(en, "get", _get)
    node = FakeNode({"passed": True, "note": "clean"})
    out = en.dispatch(node, "rtl text", "top", ["a"], name="lint")
    assert node.remote_calls and not node.local_calls
    assert isinstance(out, GateOutcome) and out.passed and out.name == "lint"
    assert out.note == "clean"


def test_dispatch_local_fallback(monkeypatch):
    monkeypatch.setattr(en, "_ray_active", lambda: False)
    node = FakeNode({"passed": True, "note": "clean"})
    out = en.dispatch(node, "rtl", "top", ["a"], name="lint")
    assert node.local_calls and not node.remote_calls
    assert out.passed


def test_connection_error_is_retry(monkeypatch):
    monkeypatch.setattr(en, "_ray_active", lambda: True)
    node = FakeNode(exc=ConnectionError("ray gcs down"))
    out = en.dispatch(node, name="lint")
    assert not out.passed and out.retry
    assert "retryable" in out.note


def test_ray_actor_error_is_retry(monkeypatch):
    monkeypatch.setattr(en, "_ray_active", lambda: True)
    node = FakeNode(exc=RuntimeError("ray::WorkerDiedError: actor died"))
    out = en.dispatch(node, name="lint")
    assert not out.passed and out.retry


def test_semantic_exception_propagates(monkeypatch):
    monkeypatch.setattr(en, "_ray_active", lambda: True)
    node = FakeNode(exc=ValueError("bug in gate code"))
    with pytest.raises(ValueError):
        en.dispatch(node, name="lint")


def test_retryable_error_is_retry(monkeypatch):
    monkeypatch.setattr(en, "_ray_active", lambda: False)
    node = FakeNode(exc=en.RetryableError("yosys binary missing"))
    out = en.dispatch(node, name="structure")
    assert not out.passed and out.retry


def test_node_dict_result_normalization(monkeypatch):
    monkeypatch.setattr(en, "_ray_active", lambda: False)
    node = FakeNode({"passed": False, "note": "x" * 900, "rc": 1})
    out = en.dispatch(node, name="area", note_len=100)
    assert not out.passed and len(out.note) == 100
    assert out.detail.get("rc") == 1


def test_dispatch_rejects_truthy_non_boolean_result(monkeypatch):
    monkeypatch.setattr(en, "_ray_active", lambda: False)
    node = FakeNode({"passed": "false", "retry": 0})
    out = en.dispatch(node, name="strict")
    assert not out.passed and not out.retry
    assert "boolean" in out.note


def test_sim_node_missing_binary_is_retryable(tmp_path):
    with pytest.raises(en.RetryableError):
        en.sim_node(["/nonexistent/tool-xyz"], str(tmp_path))


def test_lint_node_domain_neutral(tmp_path):
    rtl = ("module top(input wire clock, input wire a, output wire y);\n"
           "  assign y = a;\nendmodule\n")
    ok = en.lint_node(rtl, "top", ["clock", "a", "y"])
    assert ok["passed"], ok["errors"]
    bad = ("module top(input wire clock, output wire y);\n"
           "  initial $display(\"x\");\n  assign y = clock;\nendmodule\n"
           "initial begin end\n")
    r = en.lint_node(bad, "top", ["clock", "a", "y"])
    assert not r["passed"]
    assert any("initial/final" in e for e in r["errors"])
    assert any("missing port: a" in e for e in r["errors"])


def test_timing_probe_node_maps_fixed_json_result(tmp_path):
    command = [
        sys.executable,
        "-c",
        "import json; print(json.dumps({'passed': True, "
        "'metrics': {'setup_slack_ns': 0.2}}))",
    ]
    result = en.timing_probe_node(command, str(tmp_path))
    assert result["passed"] is True
    assert result["metrics"]["setup_slack_ns"] == 0.2


def test_timing_probe_node_rejects_malformed_output(tmp_path):
    command = [sys.executable, "-c", "print('not-json')"]
    result = en.timing_probe_node(command, str(tmp_path))
    assert result["passed"] is False
    assert result["status"] == "invalid_result"


def test_timing_probe_node_rejects_nonfinite_metrics(tmp_path):
    command = [
        sys.executable,
        "-c",
        "import json; print(json.dumps({'passed': True, "
        "'metrics': {'setup_slack_ns': float('nan')}}))",
    ]
    result = en.timing_probe_node(command, str(tmp_path))
    assert result["passed"] is False
    assert result["status"] == "invalid_result"
