"""
CLI driver for semantic equivalence analysis.

Orchestrates static fingerprinting, structural comparison, and Z3 formal
verification to determine whether two C++ files produce semantically
equivalent LLVM IR.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from semantic_equiv.compare import ComparisonResult
from semantic_equiv.fingerprint import FingerprintResult


# Lazy-import EquivalenceResult to avoid importing z3 at module level.


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class AnalysisResult:
    """Aggregate result from all analysis tiers."""

    file_a: str
    file_b: str
    function_name: str | None

    # Tier 1: static analysis (None if not run)
    fingerprint_result: FingerprintResult | None
    structural_result: ComparisonResult | None

    # Tier 2/3: Z3 formal verification (None if not run)
    z3_result: object | None  # EquivalenceResult

    # Overall
    verdict: str  # "EQUIVALENT" | "NOT_EQUIVALENT" | "UNKNOWN" | "ERROR"
    error: str | None


# ---------------------------------------------------------------------------
# Verdict derivation
# ---------------------------------------------------------------------------

_FINGERPRINT_THRESHOLD = 0.95


def derive_verdict(result: AnalysisResult) -> str:
    """Derive the overall verdict from sub-results."""
    # Z3 result takes priority when available.
    if result.z3_result is not None:
        zr = result.z3_result
        if zr.verdict == "EQUIVALENT":
            return "EQUIVALENT"
        if zr.verdict == "COUNTEREXAMPLE":
            return "NOT_EQUIVALENT"
        # Z3 UNKNOWN — fall through to static.

    # Static-only or Z3 UNKNOWN fallback.
    if result.fingerprint_result is not None:
        if result.fingerprint_result.overall_score >= _FINGERPRINT_THRESHOLD:
            return "EQUIVALENT"
        # Structural can confirm non-equivalence.
        if (result.structural_result is not None
                and not result.structural_result.equivalent):
            return "NOT_EQUIVALENT"

    if result.error:
        return "ERROR"

    return "UNKNOWN"


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="cobol-equiv",
        description="Check semantic equivalence of two C++ files via LLVM IR analysis.",
    )
    parser.add_argument("file_a", help="First C++ file")
    parser.add_argument("file_b", help="Second C++ file")
    parser.add_argument(
        "--level",
        choices=["static", "formal", "all"],
        default="all",
        help="Analysis tiers to run (default: all)",
    )
    parser.add_argument(
        "--function",
        default=None,
        metavar="NAME",
        help="Compare only this function (default: compare all)",
    )
    parser.add_argument(
        "--loop-bound",
        type=int,
        default=10,
        metavar="K",
        help="Loop unrolling bound for Z3 (default: 10)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30000,
        metavar="MS",
        help="Z3 solver timeout in milliseconds (default: 30000)",
    )
    parser.add_argument("--clang", default=None, metavar="PATH",
                        help="Path to clang binary")
    parser.add_argument("--opt", default=None, metavar="PATH",
                        help="Path to opt binary")
    parser.add_argument("--verbose", action="store_true",
                        help="Show intermediate details")
    parser.add_argument("--json", action="store_true",
                        help="Output results as JSON")
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def run_analysis(args: argparse.Namespace) -> AnalysisResult:
    """Run the requested analysis tiers and return an AnalysisResult."""
    from semantic_equiv.normalize import normalize_cpp
    from semantic_equiv.ir_parser import parse_llvm_ir
    from semantic_equiv.compare import compare_modules, compare_functions
    from semantic_equiv.fingerprint import (
        compare_modules_fingerprint,
    )

    file_a = Path(args.file_a)
    file_b = Path(args.file_b)

    # Validate files exist.
    for f in (file_a, file_b):
        if not f.is_file():
            return AnalysisResult(
                file_a=str(file_a),
                file_b=str(file_b),
                function_name=args.function,
                fingerprint_result=None,
                structural_result=None,
                z3_result=None,
                verdict="ERROR",
                error=f"File not found: {f}",
            )

    # 1. Normalize both files to LLVM IR.
    try:
        with tempfile.TemporaryDirectory(prefix="cobol_equiv_") as tmpdir:
            norm_a = normalize_cpp(
                file_a, output_dir=Path(tmpdir) / "a",
                clang_path=args.clang, opt_path=args.opt,
            )
            norm_b = normalize_cpp(
                file_b, output_dir=Path(tmpdir) / "b",
                clang_path=args.clang, opt_path=args.opt,
            )

            # 2. Parse IR.
            mod_a = parse_llvm_ir(norm_a)
            mod_b = parse_llvm_ir(norm_b)
    except SystemExit as e:
        return AnalysisResult(
            file_a=str(file_a),
            file_b=str(file_b),
            function_name=args.function,
            fingerprint_result=None,
            structural_result=None,
            z3_result=None,
            verdict="ERROR",
            error=str(e),
        )

    # 3. Run selected tiers.
    fingerprint_result = None
    structural_result = None
    z3_result = None

    run_static = args.level in ("static", "all")
    run_formal = args.level in ("formal", "all")

    if run_static:
        fingerprint_result = compare_modules_fingerprint(mod_a, mod_b)
        if args.function:
            fn_name = (
                args.function
                if args.function.startswith("@")
                else f"@{args.function}"
            )
            fn_a = mod_a.get_function(fn_name)
            fn_b = mod_b.get_function(fn_name)
            if fn_a and fn_b:
                structural_result = compare_functions(fn_a, fn_b)
            else:
                from semantic_equiv.compare import Difference
                structural_result = ComparisonResult(
                    equivalent=False,
                    differences=[Difference(
                        fn_name, "missing_function",
                        "(not found)" if fn_a is None else fn_name,
                        "(not found)" if fn_b is None else fn_name,
                    )],
                )
        else:
            structural_result = compare_modules(mod_a, mod_b)

    if run_formal:
        from semantic_equiv.z3_encoder import (
            check_equivalence_functions,
        )
        fn_name_z3 = args.function
        if fn_name_z3:
            fn_name_z3 = (
                fn_name_z3 if fn_name_z3.startswith("@")
                else f"@{fn_name_z3}"
            )
            fn_a = mod_a.get_function(fn_name_z3)
            fn_b = mod_b.get_function(fn_name_z3)
        else:
            # Default to @main, then first common function.
            fn_a = mod_a.get_function("@main")
            fn_b = mod_b.get_function("@main")
            if fn_a is None or fn_b is None:
                names_a = {fn.name for fn in mod_a.functions}
                names_b = {fn.name for fn in mod_b.functions}
                common = sorted(names_a & names_b)
                if common:
                    fn_a = mod_a.get_function(common[0])
                    fn_b = mod_b.get_function(common[0])

        if fn_a and fn_b:
            z3_result = check_equivalence_functions(
                fn_a, fn_b,
                loop_bound=args.loop_bound,
                timeout_ms=args.timeout,
            )
        else:
            from semantic_equiv.z3_encoder import EquivalenceResult
            target = fn_name_z3 or "@main"
            z3_result = EquivalenceResult(
                verdict="UNKNOWN",
                counterexample=None,
                details=f"Function {target} not found in one or both modules.",
                bounded=False,
                loop_bound=args.loop_bound,
            )

    # 4. Build result.
    result = AnalysisResult(
        file_a=str(file_a),
        file_b=str(file_b),
        function_name=args.function,
        fingerprint_result=fingerprint_result,
        structural_result=structural_result,
        z3_result=z3_result,
        verdict="",  # filled in below
        error=None,
    )
    result.verdict = derive_verdict(result)
    return result


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns exit code."""
    args = parse_args(argv)
    result = run_analysis(args)

    from semantic_equiv.report import print_report
    print_report(result, json_mode=args.json, verbose=args.verbose)

    if result.verdict == "EQUIVALENT":
        return 0
    if result.verdict == "UNKNOWN":
        return 2
    return 1  # NOT_EQUIVALENT or ERROR


if __name__ == "__main__":
    sys.exit(main())
