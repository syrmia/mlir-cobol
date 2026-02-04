#!/usr/bin/env python3
"""Tests for semantic_equiv.driver and semantic_equiv.report."""

import json
import sys
import tempfile
from pathlib import Path

# Ensure src/ is importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from semantic_equiv.driver import AnalysisResult, derive_verdict, parse_args
from semantic_equiv.report import format_terminal, format_json
from semantic_equiv.compare import ComparisonResult, Difference
from semantic_equiv.fingerprint import (
    FingerprintResult,
    FeatureScores,
)
from semantic_equiv.z3_encoder import EquivalenceResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fingerprint(score: float) -> FingerprintResult:
    """Create a FingerprintResult with a given overall score."""
    return FingerprintResult(
        overall_score=score,
        feature_scores=FeatureScores(
            io_sequence=score,
            computation_dag=score,
            cfg_shape=score,
            op_histogram=score,
            type_signature=score,
        ),
        weights={},
        matched_functions=["@main"],
        unmatched_a=[],
        unmatched_b=[],
    )


def _make_result(
    *,
    fingerprint_score: float | None = None,
    structural_equiv: bool | None = None,
    z3_verdict: str | None = None,
    z3_counterexample: dict | None = None,
    error: str | None = None,
) -> AnalysisResult:
    """Build an AnalysisResult with the given sub-results."""
    fp = _make_fingerprint(fingerprint_score) if fingerprint_score is not None else None
    sr = None
    if structural_equiv is not None:
        diffs = [] if structural_equiv else [
            Difference("@main", "opcode_mismatch", "add", "sub")
        ]
        sr = ComparisonResult(equivalent=structural_equiv, differences=diffs)
    zr = None
    if z3_verdict is not None:
        zr = EquivalenceResult(
            verdict=z3_verdict,
            counterexample=z3_counterexample,
            details="Test details.",
            bounded=False,
            loop_bound=10,
        )
    result = AnalysisResult(
        file_a="a.cpp",
        file_b="b.cpp",
        function_name=None,
        fingerprint_result=fp,
        structural_result=sr,
        z3_result=zr,
        verdict="",
        error=error,
    )
    result.verdict = derive_verdict(result)
    return result


# ---------------------------------------------------------------------------
# Argument parsing tests
# ---------------------------------------------------------------------------

def test_parse_args_defaults():
    """Default args: level=all, loop_bound=10, etc."""
    args = parse_args(["a.cpp", "b.cpp"])
    assert args.file_a == "a.cpp"
    assert args.file_b == "b.cpp"
    assert args.level == "all"
    assert args.loop_bound == 10
    assert args.timeout == 30000
    assert args.function is None
    assert args.clang is None
    assert args.opt is None
    assert not args.verbose
    assert not args.json
    print("PASS: test_parse_args_defaults")


def test_parse_args_static_only():
    """--level static sets level correctly."""
    args = parse_args(["a.cpp", "b.cpp", "--level", "static"])
    assert args.level == "static"
    print("PASS: test_parse_args_static_only")


def test_parse_args_formal_only():
    """--level formal sets level correctly."""
    args = parse_args(["a.cpp", "b.cpp", "--level", "formal"])
    assert args.level == "formal"
    print("PASS: test_parse_args_formal_only")


def test_parse_args_all_options():
    """All options set correctly."""
    args = parse_args([
        "x.cpp", "y.cpp",
        "--level", "formal",
        "--function", "add",
        "--loop-bound", "20",
        "--timeout", "5000",
        "--clang", "/usr/bin/clang",
        "--opt", "/usr/bin/opt",
        "--verbose",
        "--json",
    ])
    assert args.function == "add"
    assert args.loop_bound == 20
    assert args.timeout == 5000
    assert args.clang == "/usr/bin/clang"
    assert args.opt == "/usr/bin/opt"
    assert args.verbose
    assert args.json
    print("PASS: test_parse_args_all_options")


# ---------------------------------------------------------------------------
# Report formatting tests
# ---------------------------------------------------------------------------

def test_report_terminal_equivalent():
    """Terminal output for EQUIVALENT result."""
    result = _make_result(
        fingerprint_score=0.97,
        structural_equiv=True,
        z3_verdict="EQUIVALENT",
    )
    text = format_terminal(result)
    assert "=== Semantic Equivalence Analysis ===" in text
    assert "a.cpp vs b.cpp" in text
    assert "Overall fingerprint score:   0.97" in text
    assert "Equivalent (0 differences)" in text
    assert "EQUIVALENT" in text
    assert "VERDICT: EQUIVALENT" in text
    print("PASS: test_report_terminal_equivalent")


def test_report_terminal_counterexample():
    """Terminal output with counterexample."""
    result = _make_result(
        fingerprint_score=0.80,
        structural_equiv=False,
        z3_verdict="COUNTEREXAMPLE",
        z3_counterexample={"param_0": 5, "param_1": 3},
    )
    text = format_terminal(result)
    assert "COUNTEREXAMPLE" in text
    assert "param_0 = 5" in text
    assert "param_1 = 3" in text
    assert "VERDICT: NOT_EQUIVALENT" in text
    print("PASS: test_report_terminal_counterexample")


def test_report_json_equivalent():
    """JSON output has correct structure for EQUIVALENT."""
    result = _make_result(
        fingerprint_score=0.97,
        structural_equiv=True,
        z3_verdict="EQUIVALENT",
    )
    text = format_json(result)
    data = json.loads(text)
    assert data["verdict"] == "EQUIVALENT"
    assert data["files"]["a"] == "a.cpp"
    assert data["files"]["b"] == "b.cpp"
    assert data["static"]["fingerprint_score"] == 0.97
    assert data["static"]["structural_equivalent"] is True
    assert data["formal"]["verdict"] == "EQUIVALENT"
    assert data["error"] is None
    print("PASS: test_report_json_equivalent")


def test_report_json_counterexample():
    """JSON output includes counterexample."""
    result = _make_result(
        fingerprint_score=0.50,
        structural_equiv=False,
        z3_verdict="COUNTEREXAMPLE",
        z3_counterexample={"param_0": 5},
    )
    text = format_json(result)
    data = json.loads(text)
    assert data["verdict"] == "NOT_EQUIVALENT"
    assert data["formal"]["counterexample"] == {"param_0": 5}
    print("PASS: test_report_json_counterexample")


# ---------------------------------------------------------------------------
# Verdict logic tests
# ---------------------------------------------------------------------------

def test_verdict_logic_z3_equivalent():
    """Z3 EQUIVALENT -> overall EQUIVALENT."""
    result = _make_result(z3_verdict="EQUIVALENT")
    assert result.verdict == "EQUIVALENT"
    print("PASS: test_verdict_logic_z3_equivalent")


def test_verdict_logic_z3_counterexample():
    """Z3 COUNTEREXAMPLE -> overall NOT_EQUIVALENT."""
    result = _make_result(z3_verdict="COUNTEREXAMPLE")
    assert result.verdict == "NOT_EQUIVALENT"
    print("PASS: test_verdict_logic_z3_counterexample")


def test_verdict_logic_static_only_high():
    """Static only, score >= 0.95 -> EQUIVALENT."""
    result = _make_result(fingerprint_score=0.97, structural_equiv=True)
    assert result.verdict == "EQUIVALENT"
    print("PASS: test_verdict_logic_static_only_high")


def test_verdict_logic_static_only_low():
    """Static only, score < 0.95 -> UNKNOWN (not enough confidence)."""
    result = _make_result(fingerprint_score=0.80, structural_equiv=True)
    assert result.verdict == "UNKNOWN"
    print("PASS: test_verdict_logic_static_only_low")


def test_missing_file_error():
    """Non-existent file -> ERROR verdict."""
    args = parse_args(["nonexistent_a.cpp", "nonexistent_b.cpp"])
    # Import run_analysis here to test orchestration with missing files.
    from semantic_equiv.driver import run_analysis
    result = run_analysis(args)
    assert result.verdict == "ERROR"
    assert result.error is not None
    assert "not found" in result.error.lower() or "nonexistent" in result.error.lower()
    print("PASS: test_missing_file_error")


if __name__ == "__main__":
    test_parse_args_defaults()
    test_parse_args_static_only()
    test_parse_args_formal_only()
    test_parse_args_all_options()
    test_report_terminal_equivalent()
    test_report_terminal_counterexample()
    test_report_json_equivalent()
    test_report_json_counterexample()
    test_verdict_logic_z3_equivalent()
    test_verdict_logic_z3_counterexample()
    test_verdict_logic_static_only_high()
    test_verdict_logic_static_only_low()
    test_missing_file_error()
