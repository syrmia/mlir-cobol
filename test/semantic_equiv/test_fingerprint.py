#!/usr/bin/env python3
"""Tests for semantic_equiv.fingerprint."""

import sys
from pathlib import Path

# Ensure src/ is importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from semantic_equiv.ir_parser import parse_llvm_ir_string
from semantic_equiv.fingerprint import (
    _cosine_similarity,
    _levenshtein_distance,
    extract_type_signature,
    extract_op_histogram,
    extract_cfg_shape,
    extract_computation_dag,
    extract_io_sequence,
    fingerprint_function,
    fingerprint_module,
    compare_fingerprints,
    compare_module_fingerprints,
    compare_modules_fingerprint,
    DEFAULT_WEIGHTS,
    FeatureScores,
)


# ---------------------------------------------------------------------------
# Extraction tests
# ---------------------------------------------------------------------------

def test_type_signature():
    """Verify return type and param types extracted correctly."""
    ir = """\
define i32 @add(i32 %a, i64 %b) {
entry:
  ret i32 0
}
"""
    mod = parse_llvm_ir_string(ir)
    fn = mod.functions[0]
    sig = extract_type_signature(fn)
    assert sig.return_type == "i32", f"Expected i32, got {sig.return_type}"
    assert sig.param_types == ["i32", "i64"], f"Got {sig.param_types}"
    print("PASS: test_type_signature")


def test_op_histogram():
    """Verify opcode counts match expected."""
    ir = """\
define i32 @calc(i32 %a, i32 %b) {
entry:
  %sum = add i32 %a, %b
  %prod = mul i32 %sum, %a
  %r = add i32 %prod, %b
  ret i32 %r
}
"""
    mod = parse_llvm_ir_string(ir)
    fn = mod.functions[0]
    hist = extract_op_histogram(fn)
    assert hist.counts.get("add") == 2, f"add count: {hist.counts.get('add')}"
    assert hist.counts.get("mul") == 1, f"mul count: {hist.counts.get('mul')}"
    assert hist.counts.get("ret") == 1, f"ret count: {hist.counts.get('ret')}"
    print("PASS: test_op_histogram")


def test_cfg_shape_linear():
    """Single block: nodes=1, edges=0, back_edges=0."""
    ir = """\
define void @linear() {
entry:
  ret void
}
"""
    mod = parse_llvm_ir_string(ir)
    fn = mod.functions[0]
    shape = extract_cfg_shape(fn)
    assert shape.num_nodes == 1, f"nodes: {shape.num_nodes}"
    assert shape.num_edges == 0, f"edges: {shape.num_edges}"
    assert shape.num_back_edges == 0, f"back_edges: {shape.num_back_edges}"
    print("PASS: test_cfg_shape_linear")


def test_cfg_shape_diamond():
    """If/else diamond: nodes=4, edges=4, back_edges=0."""
    ir = """\
define void @diamond(i1 %c) {
entry:
  br i1 %c, label %left, label %right
left:
  br label %merge
right:
  br label %merge
merge:
  ret void
}
"""
    mod = parse_llvm_ir_string(ir)
    fn = mod.functions[0]
    shape = extract_cfg_shape(fn)
    assert shape.num_nodes == 4, f"nodes: {shape.num_nodes}"
    assert shape.num_edges == 4, f"edges: {shape.num_edges}"
    assert shape.num_back_edges == 0, f"back_edges: {shape.num_back_edges}"
    print("PASS: test_cfg_shape_diamond")


def test_cfg_shape_loop():
    """Loop with back-edge: back_edges=1."""
    ir = """\
define void @loop(i1 %c) {
entry:
  br label %header
header:
  br i1 %c, label %body, label %exit
body:
  br label %header
exit:
  ret void
}
"""
    mod = parse_llvm_ir_string(ir)
    fn = mod.functions[0]
    shape = extract_cfg_shape(fn)
    assert shape.num_back_edges == 1, f"back_edges: {shape.num_back_edges}"
    print("PASS: test_cfg_shape_loop")


def test_computation_dag_simple():
    """add(a, b): depth=1, nodes=1."""
    ir = """\
define i32 @simple(i32 %a, i32 %b) {
entry:
  %r = add i32 %a, %b
  ret i32 %r
}
"""
    mod = parse_llvm_ir_string(ir)
    fn = mod.functions[0]
    dag = extract_computation_dag(fn)
    # %r = add is depth 1 (params are depth 0).
    assert dag.depth == 1, f"depth: {dag.depth}"
    # Two defined names: %r from add. Ret has no result.
    # Actually only %r has a result assignment.
    assert dag.num_nodes >= 1, f"num_nodes: {dag.num_nodes}"
    print("PASS: test_computation_dag_simple")


def test_computation_dag_chain():
    """(a+b)+c: depth=2, nodes=2."""
    ir = """\
define i32 @chain(i32 %a, i32 %b, i32 %c) {
entry:
  %t = add i32 %a, %b
  %r = add i32 %t, %c
  ret i32 %r
}
"""
    mod = parse_llvm_ir_string(ir)
    fn = mod.functions[0]
    dag = extract_computation_dag(fn)
    assert dag.depth == 2, f"depth: {dag.depth}"
    assert dag.num_nodes >= 2, f"num_nodes: {dag.num_nodes}"
    print("PASS: test_computation_dag_chain")


def test_io_sequence_empty():
    """No I/O calls: empty sequence."""
    ir = """\
define i32 @no_io(i32 %a) {
entry:
  ret i32 %a
}
"""
    mod = parse_llvm_ir_string(ir)
    fn = mod.functions[0]
    io_seq = extract_io_sequence(fn)
    assert len(io_seq.operations) == 0, f"ops: {len(io_seq.operations)}"
    print("PASS: test_io_sequence_empty")


def test_io_sequence_output():
    """Call to @_ZNSolsEi: detects output:i32."""
    ir = """\
declare ptr @_ZNSolsEi(ptr, i32)
define void @print_int(ptr %os, i32 %val) {
entry:
  %r = call ptr @_ZNSolsEi(ptr %os, i32 %val)
  ret void
}
"""
    mod = parse_llvm_ir_string(ir)
    fn = mod.functions[0]
    io_seq = extract_io_sequence(fn)
    assert len(io_seq.operations) == 1, f"ops: {len(io_seq.operations)}"
    op = io_seq.operations[0]
    assert op.direction == "output", f"direction: {op.direction}"
    assert op.operand_type == "i32", f"type: {op.operand_type}"
    print("PASS: test_io_sequence_output")


# ---------------------------------------------------------------------------
# Comparison tests
# ---------------------------------------------------------------------------

def test_identical_score():
    """Same function fingerprinted twice: score = 1.0."""
    ir = """\
define i32 @add(i32 %a, i32 %b) {
entry:
  %r = add i32 %a, %b
  ret i32 %r
}
"""
    mod = parse_llvm_ir_string(ir)
    fn = mod.functions[0]
    fp = fingerprint_function(fn)
    score, _ = compare_fingerprints(fp, fp)
    assert abs(score - 1.0) < 1e-9, f"score: {score}"
    print("PASS: test_identical_score")


def test_different_score():
    """Clearly different functions: score < 0.7."""
    ir_a = """\
define i32 @foo(i32 %a, i32 %b, i32 %c) {
entry:
  %t1 = add i32 %a, %b
  %t2 = mul i32 %t1, %c
  %t3 = sub i32 %t2, %a
  ret i32 %t3
}
"""
    ir_b = """\
define void @foo(i1 %c) {
entry:
  br i1 %c, label %left, label %right
left:
  br label %merge
right:
  br label %merge
merge:
  ret void
}
"""
    mod_a = parse_llvm_ir_string(ir_a)
    mod_b = parse_llvm_ir_string(ir_b)
    fp_a = fingerprint_function(mod_a.functions[0])
    fp_b = fingerprint_function(mod_b.functions[0])
    score, _ = compare_fingerprints(fp_a, fp_b)
    assert score < 0.7, f"score should be < 0.7, got {score}"
    print("PASS: test_different_score")


def test_equivalent_commutative():
    """a+b vs b+a normalized: score = 1.0."""
    ir_a = """\
define i32 @add(i32 %a, i32 %b) {
entry:
  %r = add i32 %a, %b
  ret i32 %r
}
"""
    ir_b = """\
define i32 @add(i32 %x, i32 %y) {
entry:
  %r = add i32 %y, %x
  ret i32 %r
}
"""
    mod_a = parse_llvm_ir_string(ir_a)
    mod_b = parse_llvm_ir_string(ir_b)
    fp_a = fingerprint_function(mod_a.functions[0])
    fp_b = fingerprint_function(mod_b.functions[0])
    score, _ = compare_fingerprints(fp_a, fp_b)
    # Fingerprints should be identical since the structure is the same.
    assert abs(score - 1.0) < 1e-9, f"score: {score}"
    print("PASS: test_equivalent_commutative")


def test_cosine_similarity():
    """Unit test of _cosine_similarity with known vectors."""
    # Identical vectors -> 1.0
    v1 = {"a": 3, "b": 4}
    assert abs(_cosine_similarity(v1, v1) - 1.0) < 1e-9

    # Orthogonal vectors -> 0.0
    v2 = {"a": 1}
    v3 = {"b": 1}
    assert abs(_cosine_similarity(v2, v3)) < 1e-9

    # Empty vectors -> 1.0
    assert abs(_cosine_similarity({}, {}) - 1.0) < 1e-9

    # Known case: (1,0) vs (1,1) -> 1/sqrt(2) ~ 0.7071
    v4 = {"x": 1}
    v5 = {"x": 1, "y": 1}
    expected = 1.0 / (1.0 * 2**0.5)
    assert abs(_cosine_similarity(v4, v5) - expected) < 1e-6

    print("PASS: test_cosine_similarity")


def test_levenshtein():
    """Unit test of _levenshtein_distance."""
    assert _levenshtein_distance([], []) == 0
    assert _levenshtein_distance(["a"], []) == 1
    assert _levenshtein_distance([], ["a"]) == 1
    assert _levenshtein_distance(["a", "b"], ["a", "b"]) == 0
    assert _levenshtein_distance(["a", "b"], ["b", "a"]) == 2
    assert _levenshtein_distance(["a"], ["b"]) == 1
    assert _levenshtein_distance(["a", "b", "c"], ["a", "c"]) == 1
    print("PASS: test_levenshtein")


def test_module_comparison():
    """Two modules, verify matched/unmatched tracking."""
    ir_a = """\
define i32 @foo(i32 %a) {
entry:
  ret i32 %a
}

define i32 @bar(i32 %a) {
entry:
  ret i32 %a
}
"""
    ir_b = """\
define i32 @foo(i32 %a) {
entry:
  ret i32 %a
}

define i32 @baz(i32 %a) {
entry:
  ret i32 %a
}
"""
    mod_a = parse_llvm_ir_string(ir_a)
    mod_b = parse_llvm_ir_string(ir_b)
    result = compare_modules_fingerprint(mod_a, mod_b)
    assert "@foo" in result.matched_functions, f"matched: {result.matched_functions}"
    assert "@bar" in result.unmatched_a, f"unmatched_a: {result.unmatched_a}"
    assert "@baz" in result.unmatched_b, f"unmatched_b: {result.unmatched_b}"
    print("PASS: test_module_comparison")


def test_empty_function():
    """Zero blocks: graceful handling."""
    ir = """\
define void @empty() {
entry:
  ret void
}
"""
    mod = parse_llvm_ir_string(ir)
    fn = mod.functions[0]
    fp = fingerprint_function(fn)
    # Should not crash.
    assert fp.function_name == "@empty", f"name: {fp.function_name}"
    assert fp.cfg_shape.num_nodes == 1
    print("PASS: test_empty_function")


def test_single_ret():
    """Only ret void: minimal fingerprint."""
    ir = """\
define void @minimal() {
entry:
  ret void
}
"""
    mod = parse_llvm_ir_string(ir)
    fn = mod.functions[0]
    fp = fingerprint_function(fn)
    assert fp.type_signature.return_type == "void"
    assert fp.type_signature.param_types == []
    assert fp.op_histogram.counts.get("ret") == 1
    score, _ = compare_fingerprints(fp, fp)
    assert abs(score - 1.0) < 1e-9
    print("PASS: test_single_ret")


def test_custom_weights():
    """Custom weights affect overall score."""
    ir_a = """\
define i32 @foo(i32 %a) {
entry:
  %r = add i32 %a, 1
  ret i32 %r
}
"""
    ir_b = """\
define i64 @foo(i64 %a) {
entry:
  %r = add i64 %a, 1
  ret i64 %r
}
"""
    mod_a = parse_llvm_ir_string(ir_a)
    mod_b = parse_llvm_ir_string(ir_b)
    fp_a = fingerprint_function(mod_a.functions[0])
    fp_b = fingerprint_function(mod_b.functions[0])

    # With default weights (type_signature = 0.05).
    score_default, _ = compare_fingerprints(fp_a, fp_b)

    # With heavy type_signature weight.
    heavy_type = {
        "io_sequence": 0.0,
        "computation_dag": 0.0,
        "cfg_shape": 0.0,
        "op_histogram": 0.0,
        "type_signature": 1.0,
    }
    score_heavy, scores_heavy = compare_fingerprints(fp_a, fp_b, heavy_type)

    # Type signature should be 0.0 (different types).
    assert scores_heavy.type_signature == 0.0, f"type score: {scores_heavy.type_signature}"
    assert abs(score_heavy) < 1e-9, f"heavy score: {score_heavy}"
    assert score_default > score_heavy, (
        f"default {score_default} should be > heavy {score_heavy}"
    )
    print("PASS: test_custom_weights")


if __name__ == "__main__":
    test_type_signature()
    test_op_histogram()
    test_cfg_shape_linear()
    test_cfg_shape_diamond()
    test_cfg_shape_loop()
    test_computation_dag_simple()
    test_computation_dag_chain()
    test_io_sequence_empty()
    test_io_sequence_output()
    test_identical_score()
    test_different_score()
    test_equivalent_commutative()
    test_cosine_similarity()
    test_levenshtein()
    test_module_comparison()
    test_empty_function()
    test_single_ret()
    test_custom_weights()
