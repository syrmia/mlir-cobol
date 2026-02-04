#!/usr/bin/env python3
"""Tests for semantic_equiv.normalize."""

import os
import sys
import tempfile
from pathlib import Path

# Ensure src/ is importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from semantic_equiv.normalize import (
    compile_to_llvm_ir,
    find_llvm_tools,
    find_tool,
    normalize_cpp,
    normalize_ir,
)


def test_find_tool():
    """find_tool should locate at least 'python3' or 'python'."""
    result = find_tool("python3") or find_tool("python")
    assert result is not None, "find_tool could not locate python"
    assert result.is_file()
    print("PASS: test_find_tool")


def test_find_llvm_tools():
    """find_llvm_tools should return paths to existing clang and opt."""
    clang, opt = find_llvm_tools()
    assert clang.is_file(), f"clang not found at {clang}"
    assert opt.is_file(), f"opt not found at {opt}"
    print("PASS: test_find_llvm_tools")


def test_compile_to_llvm_ir(cpp_file: Path):
    """compile_to_llvm_ir should produce a .ll file."""
    clang, _ = find_llvm_tools()
    with tempfile.TemporaryDirectory(prefix="test_norm_") as tmpdir:
        out = Path(tmpdir) / "output.ll"
        result = compile_to_llvm_ir(cpp_file, out, clang)
        assert result.exists(), f"Expected {result} to exist"
        content = result.read_text()
        assert "define" in content, "Expected 'define' in LLVM IR output"
    print("PASS: test_compile_to_llvm_ir")


def test_normalize_ir(cpp_file: Path):
    """normalize_ir should produce a normalized .ll file."""
    clang, opt = find_llvm_tools()
    with tempfile.TemporaryDirectory(prefix="test_norm_") as tmpdir:
        raw = Path(tmpdir) / "raw.ll"
        norm = Path(tmpdir) / "norm.ll"
        compile_to_llvm_ir(cpp_file, raw, clang)
        result = normalize_ir(raw, norm, opt)
        assert result.exists(), f"Expected {result} to exist"
        content = result.read_text()
        assert "define" in content, "Expected 'define' in normalized output"
    print("PASS: test_normalize_ir")


def test_normalize_cpp(cpp_file: Path):
    """normalize_cpp should produce a normalized .ll from a .cpp."""
    with tempfile.TemporaryDirectory(prefix="test_norm_") as tmpdir:
        result = normalize_cpp(cpp_file, output_dir=tmpdir)
        assert result.exists(), f"Expected {result} to exist"
        content = result.read_text()
        assert "define" in content, "Expected 'define' in normalized output"
    print("PASS: test_normalize_cpp")


if __name__ == "__main__":
    # Accept an optional path to a C++ test file.
    if len(sys.argv) > 1:
        cpp = Path(sys.argv[1])
    else:
        cpp = Path(__file__).parent / "inputs" / "hello_equiv.cpp"

    if not cpp.exists():
        sys.exit(f"Error: test input '{cpp}' not found")

    test_find_tool()
    test_find_llvm_tools()
    test_compile_to_llvm_ir(cpp)
    test_normalize_ir(cpp)
    test_normalize_cpp(cpp)
