#!/usr/bin/env python3
"""End-to-end tests for semantic_equiv.compare using C++ files."""

import sys
import tempfile
from pathlib import Path

# Ensure src/ is importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from semantic_equiv.compare import compare_cpp_files

INPUTS_DIR = Path(__file__).parent / "inputs"


def test_equivalent_cpp():
    """add_ab.cpp vs add_ba.cpp should be equivalent (commutative add)."""
    file_a = INPUTS_DIR / "add_ab.cpp"
    file_b = INPUTS_DIR / "add_ba.cpp"
    result = compare_cpp_files(file_a, file_b, function_name="_Z3addii")
    assert result.equivalent, f"Expected equivalent: {result.summary()}"
    print("PASS: test_equivalent_cpp")


def test_nonequivalent_cpp():
    """add_ab.cpp vs a subtraction variant should not be equivalent."""
    file_a = INPUTS_DIR / "add_ab.cpp"

    # Create a temporary subtraction variant.
    with tempfile.NamedTemporaryFile(suffix=".cpp", mode="w", delete=False) as f:
        f.write("int add(int a, int b) { return a - b; }\n")
        sub_file = Path(f.name)

    try:
        result = compare_cpp_files(file_a, sub_file, function_name="_Z3addii")
        assert not result.equivalent, "Expected not equivalent"
        print("PASS: test_nonequivalent_cpp")
    finally:
        sub_file.unlink(missing_ok=True)


if __name__ == "__main__":
    test_equivalent_cpp()
    test_nonequivalent_cpp()
