"""
COBOL-to-C++ semantic equivalence bridge.

Orchestrates the full pipeline:
  COBOL source → Koopa XML → Python dicts → COBOL MLIR (xDSL)
      → EmitC MLIR → mlir-translate → generated C++
then compares the generated C++ against a reference C++ file using
the existing semantic equivalence checker.

Requires:
  - Java + koopa.jar (via KOOPA_PATH)
  - mlir-translate (via MLIR_TRANSLATE env var or PATH)
  - clang + opt (for semantic_equiv normalization)
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Tool discovery
# ---------------------------------------------------------------------------

def find_mlir_translate(override: str | None = None) -> Path | None:
    """Locate ``mlir-translate``.

    Search order:
      1. *override* argument (if provided).
      2. ``MLIR_TRANSLATE`` environment variable.
      3. Well-known LLVM directories.
      4. ``shutil.which()`` PATH lookup.

    Returns the resolved ``Path`` or ``None`` if not found.
    """
    if override:
        p = Path(override)
        if p.is_file():
            return p

    env_val = os.environ.get("MLIR_TRANSLATE")
    if env_val:
        p = Path(env_val)
        if p.is_file():
            return p

    search_dirs = [
        "/opt/homebrew/opt/llvm/bin",
        "/opt/homebrew/opt/llvm@21/bin",
        "/opt/homebrew/opt/llvm@20/bin",
        "/opt/homebrew/opt/llvm@19/bin",
        "/opt/homebrew/opt/llvm@18/bin",
        "/usr/local/opt/llvm/bin",
        "/usr/lib/llvm-19/bin",
        "/usr/lib/llvm-18/bin",
        "/usr/lib/llvm-17/bin",
        "/usr/bin",
    ]
    for d in search_dirs:
        candidate = Path(d) / "mlir-translate"
        if candidate.is_file():
            return candidate

    which = shutil.which("mlir-translate")
    if which:
        return Path(which)

    return None


def find_koopa_jar() -> Path | None:
    """Locate ``koopa.jar`` via KOOPA_PATH.

    Returns the resolved ``Path`` or ``None`` if not found.
    """
    koopa_path = os.environ.get("KOOPA_PATH", "")
    if not koopa_path:
        return None
    jar = Path(koopa_path) / "koopa.jar"
    if jar.is_file():
        return jar
    return None


def find_java() -> Path | None:
    """Locate ``java`` on PATH."""
    which = shutil.which("java")
    if which:
        return Path(which)
    return None


# ---------------------------------------------------------------------------
# Pipeline steps
# ---------------------------------------------------------------------------

@dataclass
class PipelineError:
    """Describes a failure at a specific pipeline step."""
    step: str  # "koopa" | "frontend" | "lowering" | "mlir-translate"
    message: str


def cobol_to_emitc_mlir(
    cobol_file: Path,
    work_dir: Path,
) -> tuple[str | None, PipelineError | None]:
    """Run COBOL → Koopa XML → COBOL MLIR → EmitC MLIR.

    Returns (emitc_mlir_text, None) on success, or (None, PipelineError)
    on failure.

    Note: This function modifies ``sys.path`` temporarily to import
    the compiler frontend modules from ``src/``.
    """
    # Locate project src directory relative to this file.
    src_dir = str(Path(__file__).resolve().parents[1])
    old_path = sys.path[:]
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)

    try:
        # --- Step 1: Koopa XML ---
        java = find_java()
        if java is None:
            return None, PipelineError("koopa", "Java not found on PATH")

        koopa_jar = find_koopa_jar()
        if koopa_jar is None:
            return None, PipelineError(
                "koopa",
                "koopa.jar not found. Set KOOPA_PATH to the directory "
                "containing koopa.jar.",
            )

        xml_dir = work_dir / "build_xml"
        xml_dir.mkdir(parents=True, exist_ok=True)
        stem = cobol_file.stem
        xml_file = xml_dir / f"{stem}.xml"

        result = subprocess.run(
            [str(java), "-cp", str(koopa_jar), "koopa.app.cli.ToXml",
             "--free-format", str(cobol_file), str(xml_file)],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            return None, PipelineError(
                "koopa", f"koopa failed: {result.stderr.strip()}")
        if not xml_file.is_file():
            return None, PipelineError(
                "koopa", f"koopa did not produce {xml_file}")

        # --- Step 2: XML → Python dicts → COBOL MLIR ---
        try:
            import xml.etree.ElementTree as ET
            from util.xml_handlers import process_node
            from cobol_front import emit_cobol_dialect

            tree = ET.parse(str(xml_file))
            lines = process_node(tree.getroot())
            module = emit_cobol_dialect(lines)
        except Exception as exc:
            return None, PipelineError(
                "frontend", f"COBOL frontend failed: {exc}")

        # --- Step 3: COBOL MLIR → EmitC MLIR ---
        try:
            from emitc_lowering import lower_to_emitc

            emitc_module = lower_to_emitc(module)
            if emitc_module is None:
                return None, PipelineError(
                    "lowering", "lower_to_emitc returned None")
            emitc_text = str(emitc_module)
        except Exception as exc:
            return None, PipelineError(
                "lowering", f"EmitC lowering failed: {exc}")

        return emitc_text, None

    finally:
        sys.path[:] = old_path


def emitc_to_cpp(
    emitc_text: str,
    work_dir: Path,
    mlir_translate_path: Path | None = None,
) -> tuple[Path | None, PipelineError | None]:
    """Convert EmitC MLIR text to C++ via ``mlir-translate --mlir-to-cpp``.

    Returns (cpp_path, None) on success, or (None, PipelineError) on failure.
    """
    translate = mlir_translate_path or find_mlir_translate()
    if translate is None:
        return None, PipelineError(
            "mlir-translate",
            "mlir-translate not found. Set MLIR_TRANSLATE env var or "
            "install LLVM.",
        )

    work_dir.mkdir(parents=True, exist_ok=True)

    mlir_file = work_dir / "emitc.mlir"
    cpp_file = work_dir / "generated.cpp"

    mlir_file.write_text(emitc_text)

    result = subprocess.run(
        [str(translate), "--mlir-to-cpp", str(mlir_file)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return None, PipelineError(
            "mlir-translate",
            f"mlir-translate failed: {result.stderr.strip()}",
        )

    cpp_file.write_text(result.stdout)
    return cpp_file, None


def cobol_to_cpp(
    cobol_file: Path,
    work_dir: Path,
    mlir_translate_path: Path | None = None,
) -> tuple[Path | None, PipelineError | None]:
    """Full pipeline: COBOL → C++.

    Returns (cpp_path, None) on success, or (None, PipelineError) on failure.
    """
    emitc_text, err = cobol_to_emitc_mlir(cobol_file, work_dir)
    if err is not None:
        return None, err

    return emitc_to_cpp(emitc_text, work_dir, mlir_translate_path)


# ---------------------------------------------------------------------------
# Equivalence check
# ---------------------------------------------------------------------------

@dataclass
class CobolEquivResult:
    """Result of comparing COBOL-generated C++ against a reference C++ file."""

    # Pipeline info
    cobol_file: str
    reference_file: str
    generated_cpp: str | None  # path to generated C++, if pipeline succeeded

    # Pipeline error (None if pipeline succeeded)
    pipeline_error: PipelineError | None

    # Equivalence analysis result (None if pipeline failed)
    analysis: object | None  # AnalysisResult from driver

    # Overall verdict
    verdict: str  # "EQUIVALENT" | "NOT_EQUIVALENT" | "UNKNOWN" | "ERROR"
    error: str | None


def check_cobol_equiv(
    cobol_file: str | Path,
    reference_cpp: str | Path,
    *,
    function: str | None = None,
    level: str = "all",
    loop_bound: int = 10,
    timeout: int = 30000,
    clang: str | None = None,
    opt: str | None = None,
    mlir_translate: str | None = None,
    work_dir: str | Path | None = None,
) -> CobolEquivResult:
    """Compare COBOL source against reference C++ for semantic equivalence.

    This is the main public API of the bridge module.

    Parameters
    ----------
    cobol_file : path to COBOL source (.cbl)
    reference_cpp : path to reference C++ file
    function : specific function name to compare (default: all / @main)
    level : analysis tier — "static", "formal", or "all"
    loop_bound : Z3 loop unrolling bound
    timeout : Z3 solver timeout in ms
    clang : path to clang binary override
    opt : path to opt binary override
    mlir_translate : path to mlir-translate binary override
    work_dir : directory for intermediate files (default: temp dir)

    Returns
    -------
    CobolEquivResult
    """
    cobol_file = Path(cobol_file)
    reference_cpp = Path(reference_cpp)

    if not cobol_file.is_file():
        return CobolEquivResult(
            cobol_file=str(cobol_file),
            reference_file=str(reference_cpp),
            generated_cpp=None,
            pipeline_error=None,
            analysis=None,
            verdict="ERROR",
            error=f"COBOL file not found: {cobol_file}",
        )

    if not reference_cpp.is_file():
        return CobolEquivResult(
            cobol_file=str(cobol_file),
            reference_file=str(reference_cpp),
            generated_cpp=None,
            pipeline_error=None,
            analysis=None,
            verdict="ERROR",
            error=f"Reference C++ file not found: {reference_cpp}",
        )

    # Set up working directory.
    cleanup_dir = False
    if work_dir is None:
        work_dir = Path(tempfile.mkdtemp(prefix="cobol_equiv_"))
        cleanup_dir = True
    else:
        work_dir = Path(work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)

    try:
        # --- Step 1: COBOL → C++ ---
        gen_cpp, pipe_err = cobol_to_cpp(
            cobol_file, work_dir,
            mlir_translate_path=Path(mlir_translate) if mlir_translate else None,
        )

        if pipe_err is not None:
            return CobolEquivResult(
                cobol_file=str(cobol_file),
                reference_file=str(reference_cpp),
                generated_cpp=None,
                pipeline_error=pipe_err,
                analysis=None,
                verdict="ERROR",
                error=f"Pipeline failed at {pipe_err.step}: {pipe_err.message}",
            )

        # --- Step 2: Equivalence check ---
        import argparse
        from semantic_equiv.driver import run_analysis

        # Build a Namespace matching what run_analysis expects.
        args = argparse.Namespace(
            file_a=str(gen_cpp),
            file_b=str(reference_cpp),
            function=function,
            level=level,
            loop_bound=loop_bound,
            timeout=timeout,
            clang=clang,
            opt=opt,
            verbose=False,
            json=False,
        )

        analysis_result = run_analysis(args)

        return CobolEquivResult(
            cobol_file=str(cobol_file),
            reference_file=str(reference_cpp),
            generated_cpp=str(gen_cpp),
            pipeline_error=None,
            analysis=analysis_result,
            verdict=analysis_result.verdict,
            error=analysis_result.error,
        )

    except Exception as exc:
        return CobolEquivResult(
            cobol_file=str(cobol_file),
            reference_file=str(reference_cpp),
            generated_cpp=None,
            pipeline_error=None,
            analysis=None,
            verdict="ERROR",
            error=f"Unexpected error: {exc}",
        )

    finally:
        if cleanup_dir:
            import shutil as _shutil
            _shutil.rmtree(work_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    import argparse as _argparse

    parser = _argparse.ArgumentParser(
        prog="cobol-verify",
        description=(
            "Check semantic equivalence of COBOL source against reference C++ "
            "by compiling COBOL through the MLIR pipeline and comparing "
            "the generated C++ at the LLVM IR level."
        ),
    )
    parser.add_argument("cobol_file", help="Input COBOL source file (.cbl)")
    parser.add_argument("reference_cpp", help="Reference C++ file")
    parser.add_argument(
        "--level", choices=["static", "formal", "all"], default="all",
        help="Analysis tiers to run (default: all)",
    )
    parser.add_argument(
        "--function", default=None, metavar="NAME",
        help="Compare only this function (default: compare all)",
    )
    parser.add_argument(
        "--loop-bound", type=int, default=10, metavar="K",
        help="Loop unrolling bound for Z3 (default: 10)",
    )
    parser.add_argument(
        "--timeout", type=int, default=30000, metavar="MS",
        help="Z3 solver timeout in milliseconds (default: 30000)",
    )
    parser.add_argument("--clang", default=None, metavar="PATH",
                        help="Path to clang binary")
    parser.add_argument("--opt", default=None, metavar="PATH",
                        help="Path to opt binary")
    parser.add_argument("--mlir-translate", default=None, metavar="PATH",
                        help="Path to mlir-translate binary")
    parser.add_argument("--verbose", action="store_true",
                        help="Show intermediate details")
    parser.add_argument("--json", action="store_true",
                        help="Output results as JSON")
    parser.add_argument("--work-dir", default=None, metavar="DIR",
                        help="Directory for intermediate files")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns exit code."""
    args = parse_args(argv)

    result = check_cobol_equiv(
        cobol_file=args.cobol_file,
        reference_cpp=args.reference_cpp,
        function=args.function,
        level=args.level,
        loop_bound=args.loop_bound,
        timeout=args.timeout,
        clang=args.clang,
        opt=args.opt,
        mlir_translate=getattr(args, "mlir_translate", None),
        work_dir=args.work_dir,
    )

    # Print report.
    if result.pipeline_error:
        print(f"PIPELINE ERROR [{result.pipeline_error.step}]: "
              f"{result.pipeline_error.message}")
    elif result.analysis is not None:
        from semantic_equiv.report import print_report
        print_report(
            result.analysis,
            json_mode=args.json,
            verbose=args.verbose,
        )
    else:
        print(f"ERROR: {result.error}")

    if result.verdict == "EQUIVALENT":
        return 0
    if result.verdict == "UNKNOWN":
        return 2
    return 1  # NOT_EQUIVALENT or ERROR


if __name__ == "__main__":
    sys.exit(main())
