#!/usr/bin/env python3
"""Tests for semantic_equiv.compare."""

import sys
from pathlib import Path

# Ensure src/ is importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from semantic_equiv.ir_parser import parse_llvm_ir_string
from semantic_equiv.compare import compare_modules, compare_functions


def test_identical_modules():
    """Two identical IR modules should be equivalent."""
    ir = """\
define i32 @add(i32 %a, i32 %b) {
entry:
  %sum = add i32 %a, %b
  ret i32 %sum
}
"""
    mod_a = parse_llvm_ir_string(ir)
    mod_b = parse_llvm_ir_string(ir)
    result = compare_modules(mod_a, mod_b)
    assert result.equivalent, f"Expected equivalent: {result.summary()}"
    print("PASS: test_identical_modules")


def test_alpha_renamed():
    """Same structure with different SSA names should be equivalent."""
    ir_a = """\
define i32 @foo(i32 %a, i32 %b) {
entry:
  %sum = add i32 %a, %b
  ret i32 %sum
}
"""
    ir_b = """\
define i32 @foo(i32 %x, i32 %y) {
entry:
  %result = add i32 %x, %y
  ret i32 %result
}
"""
    mod_a = parse_llvm_ir_string(ir_a)
    mod_b = parse_llvm_ir_string(ir_b)
    result = compare_modules(mod_a, mod_b)
    assert result.equivalent, f"Expected equivalent: {result.summary()}"
    print("PASS: test_alpha_renamed")


def test_different_labels():
    """Same structure with different block labels should be equivalent."""
    ir_a = """\
define void @test(i1 %c) {
entry:
  br i1 %c, label %then, label %else
then:
  br label %end
else:
  br label %end
end:
  ret void
}
"""
    ir_b = """\
define void @test(i1 %cond) {
bb0:
  br i1 %cond, label %bb1, label %bb2
bb1:
  br label %bb3
bb2:
  br label %bb3
bb3:
  ret void
}
"""
    mod_a = parse_llvm_ir_string(ir_a)
    mod_b = parse_llvm_ir_string(ir_b)
    result = compare_modules(mod_a, mod_b)
    assert result.equivalent, f"Expected equivalent: {result.summary()}"
    print("PASS: test_different_labels")


def test_commutative_ops():
    """add %a, %b vs add %b, %a should be equivalent."""
    ir_a = """\
define i32 @foo(i32 %a, i32 %b) {
entry:
  %r = add i32 %a, %b
  ret i32 %r
}
"""
    ir_b = """\
define i32 @foo(i32 %a, i32 %b) {
entry:
  %r = add i32 %b, %a
  ret i32 %r
}
"""
    mod_a = parse_llvm_ir_string(ir_a)
    mod_b = parse_llvm_ir_string(ir_b)
    result = compare_modules(mod_a, mod_b)
    assert result.equivalent, f"Expected equivalent: {result.summary()}"
    print("PASS: test_commutative_ops")


def test_predicate_swap():
    """icmp slt %a, %b vs icmp sgt %b, %a should be equivalent."""
    ir_a = """\
define i1 @cmp(i32 %a, i32 %b) {
entry:
  %r = icmp slt i32 %a, %b
  ret i1 %r
}
"""
    ir_b = """\
define i1 @cmp(i32 %x, i32 %y) {
entry:
  %r = icmp sgt i32 %y, %x
  ret i1 %r
}
"""
    mod_a = parse_llvm_ir_string(ir_a)
    mod_b = parse_llvm_ir_string(ir_b)
    result = compare_modules(mod_a, mod_b)
    assert result.equivalent, f"Expected equivalent: {result.summary()}"
    print("PASS: test_predicate_swap")


def test_opcode_mismatch():
    """add vs sub should report a difference."""
    ir_a = """\
define i32 @foo(i32 %a, i32 %b) {
entry:
  %r = add i32 %a, %b
  ret i32 %r
}
"""
    ir_b = """\
define i32 @foo(i32 %a, i32 %b) {
entry:
  %r = sub i32 %a, %b
  ret i32 %r
}
"""
    mod_a = parse_llvm_ir_string(ir_a)
    mod_b = parse_llvm_ir_string(ir_b)
    result = compare_modules(mod_a, mod_b)
    assert not result.equivalent, "Expected not equivalent"
    assert any(d.kind == "opcode_mismatch" for d in result.differences)
    print("PASS: test_opcode_mismatch")


def test_missing_function():
    """Extra function in one module should report a difference."""
    ir_a = """\
define void @foo() {
entry:
  ret void
}

define void @bar() {
entry:
  ret void
}
"""
    ir_b = """\
define void @foo() {
entry:
  ret void
}
"""
    mod_a = parse_llvm_ir_string(ir_a)
    mod_b = parse_llvm_ir_string(ir_b)
    result = compare_modules(mod_a, mod_b)
    assert not result.equivalent, "Expected not equivalent"
    assert any(d.kind == "missing_function" for d in result.differences)
    print("PASS: test_missing_function")


def test_different_return_type():
    """i32 vs i64 return type should report a difference."""
    ir_a = """\
define i32 @foo() {
entry:
  ret i32 0
}
"""
    ir_b = """\
define i64 @foo() {
entry:
  ret i64 0
}
"""
    mod_a = parse_llvm_ir_string(ir_a)
    mod_b = parse_llvm_ir_string(ir_b)
    result = compare_modules(mod_a, mod_b)
    assert not result.equivalent, "Expected not equivalent"
    assert any(d.kind == "return_type" for d in result.differences)
    print("PASS: test_different_return_type")


def test_different_constants():
    """add i32 %x, 1 vs add i32 %x, 2 should not be equivalent."""
    ir_a = """\
define i32 @foo(i32 %x) {
entry:
  %r = add i32 %x, 1
  ret i32 %r
}
"""
    ir_b = """\
define i32 @foo(i32 %x) {
entry:
  %r = add i32 %x, 2
  ret i32 %r
}
"""
    mod_a = parse_llvm_ir_string(ir_a)
    mod_b = parse_llvm_ir_string(ir_b)
    result = compare_modules(mod_a, mod_b)
    assert not result.equivalent, "Expected not equivalent"
    assert any(d.kind == "operand_mismatch" for d in result.differences)
    print("PASS: test_different_constants")


def test_phi_reorder():
    """Phi incoming pairs in different order should be equivalent."""
    ir_a = """\
define i32 @phi_test(i1 %c) {
entry:
  br i1 %c, label %left, label %right
left:
  br label %merge
right:
  br label %merge
merge:
  %v = phi i32 [ 1, %left ], [ 2, %right ]
  ret i32 %v
}
"""
    ir_b = """\
define i32 @phi_test(i1 %cond) {
bb0:
  br i1 %cond, label %bb1, label %bb2
bb1:
  br label %bb3
bb2:
  br label %bb3
bb3:
  %val = phi i32 [ 2, %bb2 ], [ 1, %bb1 ]
  ret i32 %val
}
"""
    mod_a = parse_llvm_ir_string(ir_a)
    mod_b = parse_llvm_ir_string(ir_b)
    result = compare_modules(mod_a, mod_b)
    assert result.equivalent, f"Expected equivalent: {result.summary()}"
    print("PASS: test_phi_reorder")


def test_call_different_callee():
    """Calls to @foo vs @bar should not be equivalent."""
    ir_a = """\
declare i32 @foo()
define i32 @test() {
entry:
  %r = call i32 @foo()
  ret i32 %r
}
"""
    ir_b = """\
declare i32 @bar()
define i32 @test() {
entry:
  %r = call i32 @bar()
  ret i32 %r
}
"""
    mod_a = parse_llvm_ir_string(ir_a)
    mod_b = parse_llvm_ir_string(ir_b)
    result = compare_modules(mod_a, mod_b)
    assert not result.equivalent, "Expected not equivalent"
    assert any(d.kind == "callee_mismatch" for d in result.differences)
    print("PASS: test_call_different_callee")


def test_summary_output():
    """Verify the summary string contains useful info."""
    ir_a = """\
define i32 @foo() {
entry:
  ret i32 0
}
"""
    ir_b = """\
define i64 @foo() {
entry:
  ret i64 0
}
"""
    mod_a = parse_llvm_ir_string(ir_a)
    mod_b = parse_llvm_ir_string(ir_b)
    result = compare_modules(mod_a, mod_b)
    summary = result.summary()
    assert "differ" in summary
    assert "return_type" in summary
    assert "i32" in summary
    assert "i64" in summary
    print("PASS: test_summary_output")


if __name__ == "__main__":
    test_identical_modules()
    test_alpha_renamed()
    test_different_labels()
    test_commutative_ops()
    test_predicate_swap()
    test_opcode_mismatch()
    test_missing_function()
    test_different_return_type()
    test_different_constants()
    test_phi_reorder()
    test_call_different_callee()
    test_summary_output()
