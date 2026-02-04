"""
Normalize C++ source to canonical LLVM IR via clang and opt.

Provides helpers to locate clang/opt, compile C++ to LLVM IR, and run
a fixed set of optimization passes to produce a normalized form suitable
for semantic comparison.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


# Common search paths for LLVM tools (macOS Homebrew, Linux system packages).
_LLVM_SEARCH_DIRS = [
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

# Normalization passes applied by opt.
_NORMALIZE_PASSES = "mem2reg,instcombine,simplifycfg,dce,reassociate"


def find_tool(name: str, env_var: str | None = None) -> Path | None:
    """Locate an LLVM tool by *name*.

    Search order:
    1. Environment variable *env_var* (if provided and set).
    2. Well-known LLVM directories (Homebrew, system packages).
    3. ``shutil.which()`` (PATH lookup).

    Returns the resolved ``Path`` or ``None`` if not found.
    """
    # 1. Environment variable override.
    if env_var:
        val = os.environ.get(env_var)
        if val:
            p = Path(val)
            if p.is_file():
                return p

    # 2. Well-known directories.
    for d in _LLVM_SEARCH_DIRS:
        candidate = Path(d) / name
        if candidate.is_file():
            return candidate

    # 3. PATH lookup.
    which = shutil.which(name)
    if which:
        return Path(which)

    return None


def find_llvm_tools(
    clang_override: str | None = None,
    opt_override: str | None = None,
) -> tuple[Path, Path]:
    """Find ``clang`` and ``opt`` from the same LLVM installation.

    If *clang_override* / *opt_override* are given they take priority.
    Otherwise the function tries to pick both tools from the same
    directory so that version mismatches are avoided.

    Exits with a helpful diagnostic if either tool cannot be found.
    """
    if clang_override:
        clang = Path(clang_override)
    else:
        clang = find_tool("clang", "CLANG_PATH")

    if opt_override:
        opt = Path(opt_override)
    else:
        opt = find_tool("opt", "OPT_PATH")

    # If we found clang but not opt (or vice-versa), try the sibling.
    if clang and not opt:
        sibling = clang.parent / "opt"
        if sibling.is_file():
            opt = sibling
    elif opt and not clang:
        sibling = opt.parent / "clang"
        if sibling.is_file():
            clang = sibling

    if not clang:
        sys.exit(
            "Error: could not find 'clang'.\n"
            "Set the CLANG_PATH environment variable or install LLVM:\n"
            "  macOS:  brew install llvm\n"
            "  Linux:  apt install clang"
        )
    if not opt:
        sys.exit(
            "Error: could not find 'opt'.\n"
            "Set the OPT_PATH environment variable or install LLVM:\n"
            "  macOS:  brew install llvm\n"
            "  Linux:  apt install llvm"
        )

    return clang, opt


def compile_to_llvm_ir(
    cpp_file: str | Path,
    output_file: str | Path,
    clang_path: str | Path,
) -> Path:
    """Compile *cpp_file* to unoptimised LLVM IR using *clang_path*.

    The generated ``.ll`` file is written to *output_file*.
    Returns the output path on success; exits on failure.
    """
    cpp_file = Path(cpp_file)
    output_file = Path(output_file)
    clang_path = Path(clang_path)

    result = subprocess.run(
        [str(clang_path), "-S", "-emit-llvm", "-O0",
         "-Xclang", "-disable-O0-optnone",
         str(cpp_file), "-o", str(output_file)],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        sys.exit(
            f"Error: clang failed on '{cpp_file}':\n{result.stderr}"
        )

    return output_file


def normalize_ir(
    ir_file: str | Path,
    output_file: str | Path,
    opt_path: str | Path,
) -> Path:
    """Run normalizing passes on *ir_file* using *opt_path*.

    Writes the result to *output_file* and returns its path.
    """
    ir_file = Path(ir_file)
    output_file = Path(output_file)
    opt_path = Path(opt_path)

    result = subprocess.run(
        [str(opt_path),
         f"-passes={_NORMALIZE_PASSES}",
         str(ir_file), "-S", "-o", str(output_file)],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        sys.exit(
            f"Error: opt failed on '{ir_file}':\n{result.stderr}"
        )

    return output_file


def normalize_cpp(
    cpp_file: str | Path,
    output_dir: str | Path | None = None,
    clang_path: str | Path | None = None,
    opt_path: str | Path | None = None,
) -> Path:
    """Compile and normalize a C++ file to canonical LLVM IR.

    This is the main public entry point combining :func:`compile_to_llvm_ir`
    and :func:`normalize_ir`.

    Returns the path to the normalized ``.ll`` file.
    """
    cpp_file = Path(cpp_file)

    if clang_path and opt_path:
        clang, opt = Path(clang_path), Path(opt_path)
    else:
        clang, opt = find_llvm_tools(
            clang_override=str(clang_path) if clang_path else None,
            opt_override=str(opt_path) if opt_path else None,
        )

    if output_dir is None:
        output_dir = Path(tempfile.mkdtemp(prefix="semantic_equiv_"))
    else:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

    stem = cpp_file.stem
    raw_ir = output_dir / f"{stem}_raw.ll"
    norm_ir = output_dir / f"{stem}_norm.ll"

    compile_to_llvm_ir(cpp_file, raw_ir, clang)
    normalize_ir(raw_ir, norm_ir, opt)

    return norm_ir
