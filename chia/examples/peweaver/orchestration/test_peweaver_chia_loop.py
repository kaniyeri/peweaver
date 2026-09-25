"""Provenance guards for the bounded native CHIA generation loop."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from peweaver_chia_loop import (  # noqa: E402
    CONTRACT,
    HISTORICAL_CANDIDATE_HASHES,
    REFERENCE_FILES,
    build_prompt,
    extract_verilog,
)


def test_extract_requires_a_verilog_candidate():
    assert extract_verilog("analysis only") == ""
    assert extract_verilog("```verilog\nmodule peweaver_shared_fft;\nendmodule\n```").startswith(
        "module peweaver_shared_fft"
    )


def test_prompt_contains_references_but_not_historical_candidate(tmp_path):
    for relative in REFERENCE_FILES:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"module {path.stem}; endmodule\n")
    prompt = build_prompt(tmp_path)
    assert CONTRACT in prompt
    assert "No pre-existing shared candidate is supplied" in prompt
    for historical_hash in HISTORICAL_CANDIDATE_HASHES:
        assert historical_hash not in prompt


def test_prompt_repair_context_is_only_prior_generated_text(tmp_path):
    for relative in REFERENCE_FILES:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("module reference; endmodule\n")
    prompt = build_prompt(tmp_path, "module generated; endmodule\n", "lint failed")
    assert "PRIOR GENERATED CANDIDATE" in prompt
    assert "module generated" in prompt
    assert "lint failed" in prompt
