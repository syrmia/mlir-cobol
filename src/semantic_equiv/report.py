"""
Output formatting for semantic equivalence analysis results.

Provides terminal (human-readable) and JSON output modes for
AnalysisResult objects produced by the driver.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from semantic_equiv.driver import AnalysisResult


def format_terminal(result: AnalysisResult, verbose: bool = False) -> str:
    """Format an AnalysisResult as a human-readable terminal string."""
    lines: list[str] = []
    lines.append("=== Semantic Equivalence Analysis ===")
    lines.append(f"Files: {result.file_a} vs {result.file_b}")
    if result.function_name:
        lines.append(f"Function: {result.function_name}")
    lines.append("")

    # Tier 1: Static Fingerprinting
    if result.fingerprint_result is not None:
        fp = result.fingerprint_result
        lines.append("--- Tier 1: Static Fingerprinting ---")
        fs = fp.feature_scores
        lines.append(f"  I/O pattern similarity:      {fs.io_sequence:.2f}")
        lines.append(f"  Computation DAG similarity:  {fs.computation_dag:.2f}")
        lines.append(f"  CFG shape similarity:        {fs.cfg_shape:.2f}")
        lines.append(f"  Operation histogram:         {fs.op_histogram:.2f}")
        lines.append(f"  Type signature match:        {fs.type_signature:.2f}")
        lines.append(f"  Overall fingerprint score:   {fp.overall_score:.2f}")
        if verbose and (fp.unmatched_a or fp.unmatched_b):
            if fp.unmatched_a:
                lines.append(f"  Unmatched in A: {', '.join(fp.unmatched_a)}")
            if fp.unmatched_b:
                lines.append(f"  Unmatched in B: {', '.join(fp.unmatched_b)}")
        lines.append("")

    # Tier 1: Structural Comparison
    if result.structural_result is not None:
        sr = result.structural_result
        lines.append("--- Tier 1: Structural Comparison ---")
        if sr.equivalent:
            lines.append(f"  Result: Equivalent ({len(sr.differences)} differences)")
        else:
            lines.append(
                f"  Result: Not equivalent ({len(sr.differences)} difference(s))"
            )
            if verbose:
                for d in sr.differences[:10]:
                    lines.append(f"    {d}")
        lines.append("")

    # Tier 2: Z3 Formal Verification
    if result.z3_result is not None:
        zr = result.z3_result
        lines.append("--- Tier 2: Z3 Formal Verification ---")
        lines.append(f"  Loop bound:      {zr.loop_bound}")
        lines.append(f"  Bounded proof:   {'Yes' if zr.bounded else 'No'}")
        lines.append(f"  Solver result:   {zr.verdict}")
        lines.append(f"  Details:         {zr.details}")
        if zr.counterexample:
            lines.append("  Counterexample:")
            for k, v in sorted(zr.counterexample.items()):
                lines.append(f"    {k} = {v}")
        lines.append("")

    # Error
    if result.error:
        lines.append(f"Error: {result.error}")
        lines.append("")

    # Overall verdict
    lines.append(f"=== VERDICT: {result.verdict} ===")
    return "\n".join(lines)


def format_json(result: AnalysisResult) -> str:
    """Format an AnalysisResult as a JSON string."""
    data: dict = {
        "verdict": result.verdict,
        "files": {"a": result.file_a, "b": result.file_b},
        "function": result.function_name,
    }

    if result.fingerprint_result is not None:
        fp = result.fingerprint_result
        fs = fp.feature_scores
        static: dict = {
            "fingerprint_score": fp.overall_score,
            "feature_scores": {
                "io_sequence": fs.io_sequence,
                "computation_dag": fs.computation_dag,
                "cfg_shape": fs.cfg_shape,
                "op_histogram": fs.op_histogram,
                "type_signature": fs.type_signature,
            },
        }
        if result.structural_result is not None:
            static["structural_equivalent"] = result.structural_result.equivalent
        data["static"] = static
    else:
        data["static"] = None

    if result.z3_result is not None:
        zr = result.z3_result
        data["formal"] = {
            "verdict": zr.verdict,
            "bounded": zr.bounded,
            "loop_bound": zr.loop_bound,
            "details": zr.details,
            "counterexample": zr.counterexample,
        }
    else:
        data["formal"] = None

    data["error"] = result.error

    return json.dumps(data, indent=2)


def print_report(
    result: AnalysisResult,
    json_mode: bool = False,
    verbose: bool = False,
) -> None:
    """Print formatted analysis results to stdout."""
    if json_mode:
        print(format_json(result))
    else:
        print(format_terminal(result, verbose=verbose))
