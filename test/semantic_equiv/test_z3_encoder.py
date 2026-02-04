#!/usr/bin/env python3
"""Tests for semantic_equiv.z3_encoder."""

import sys
from pathlib import Path

# Ensure src/ is importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import z3

from semantic_equiv.ir_parser import parse_llvm_ir_string
from semantic_equiv.z3_encoder import (
    Z3Encoder,
    check_equivalence,
    check_equivalence_functions,
    encode_function,
    EncodingResult,
    EquivalenceResult,
    SymbolicInput,
    SymbolicOutput,
)


def _z3_equiv(a, b):
    """Check if two Z3 expressions are always equal."""
    s = z3.Solver()
    s.add(a != b)
    return s.check() == z3.unsat


# ---------------------------------------------------------------------------
# Encoding tests
# ---------------------------------------------------------------------------

def test_encode_simple_add():
    """add i32 %a, %b; ret — encode and check result expr."""
    ir = """\
define i32 @add(i32 %a, i32 %b) {
entry:
  %r = add i32 %a, %b
  ret i32 %r
}
"""
    mod = parse_llvm_ir_string(ir)
    fn = mod.functions[0]
    result = encode_function(fn)

    assert result.function_name == "@add", f"name: {result.function_name}"
    assert result.return_expr is not None, "return_expr is None"
    assert not result.has_unsupported, f"unsupported: {result.unsupported_opcodes}"

    # Return expr should be equivalent to %a + %b.
    expected = z3.Int("%a") + z3.Int("%b")
    assert _z3_equiv(result.return_expr, expected), (
        f"Expected {expected}, got {result.return_expr}"
    )
    print("PASS: test_encode_simple_add")


def test_encode_icmp_predicates():
    """icmp slt/sgt/eq — verify boolean Z3 expressions."""
    ir = """\
define i32 @cmp(i32 %a, i32 %b) {
entry:
  %lt = icmp slt i32 %a, %b
  %gt = icmp sgt i32 %a, %b
  %eq = icmp eq i32 %a, %b
  ret i32 0
}
"""
    mod = parse_llvm_ir_string(ir)
    fn = mod.functions[0]
    enc = Z3Encoder()
    result = enc.encode_function(fn)

    a = z3.Int("%a")
    b = z3.Int("%b")

    # %lt should be If(a < b, 1, 0)
    lt_expr = enc._env["%lt"]
    expected_lt = z3.If(a < b, z3.IntVal(1), z3.IntVal(0))
    assert _z3_equiv(lt_expr, expected_lt), f"slt: {lt_expr}"

    # %gt should be If(a > b, 1, 0)
    gt_expr = enc._env["%gt"]
    expected_gt = z3.If(a > b, z3.IntVal(1), z3.IntVal(0))
    assert _z3_equiv(gt_expr, expected_gt), f"sgt: {gt_expr}"

    # %eq should be If(a == b, 1, 0)
    eq_expr = enc._env["%eq"]
    expected_eq = z3.If(a == b, z3.IntVal(1), z3.IntVal(0))
    assert _z3_equiv(eq_expr, expected_eq), f"eq: {eq_expr}"

    print("PASS: test_encode_icmp_predicates")


def test_encode_select():
    """select i1 %c, i32 %a, i32 %b -> If(c, a, b)."""
    ir = """\
define i32 @sel(i32 %a, i32 %b, i1 %c) {
entry:
  %r = select i1 %c, i32 %a, i32 %b
  ret i32 %r
}
"""
    mod = parse_llvm_ir_string(ir)
    fn = mod.functions[0]
    result = encode_function(fn)

    a = z3.Int("%a")
    b = z3.Int("%b")
    c = z3.Int("%c")
    expected = z3.If(c != z3.IntVal(0), a, b)
    assert _z3_equiv(result.return_expr, expected), (
        f"Expected If(c!=0, a, b), got {result.return_expr}"
    )
    print("PASS: test_encode_select")


def test_encode_phi_node():
    """phi with 2 incoming -> If(pred_cond, v1, v2)."""
    ir = """\
define i32 @phi_test(i1 %c, i32 %a, i32 %b) {
entry:
  br i1 %c, label %left, label %right
left:
  br label %merge
right:
  br label %merge
merge:
  %r = phi i32 [ %a, %left ], [ %b, %right ]
  ret i32 %r
}
"""
    mod = parse_llvm_ir_string(ir)
    fn = mod.functions[0]
    result = encode_function(fn)

    a = z3.Int("%a")
    b = z3.Int("%b")
    c = z3.Int("%c")
    # Phi should resolve to If(cond_from_left, %a, %b).
    # cond_from_left = path_cond[left] = (c != 0).
    expected = z3.If(c != z3.IntVal(0), a, b)
    assert _z3_equiv(result.return_expr, expected), (
        f"Expected If(c!=0, a, b), got {result.return_expr}"
    )
    print("PASS: test_encode_phi_node")


def test_encode_conditional_branch():
    """Diamond CFG with phi merge — verify path conditions."""
    ir = """\
define i32 @diamond(i1 %c, i32 %a, i32 %b) {
entry:
  br i1 %c, label %then, label %else
then:
  %t = add i32 %a, 1
  br label %merge
else:
  %e = add i32 %b, 2
  br label %merge
merge:
  %r = phi i32 [ %t, %then ], [ %e, %else ]
  ret i32 %r
}
"""
    mod = parse_llvm_ir_string(ir)
    fn = mod.functions[0]
    result = encode_function(fn)

    a = z3.Int("%a")
    b = z3.Int("%b")
    c = z3.Int("%c")
    expected = z3.If(c != z3.IntVal(0), a + 1, b + 2)
    assert _z3_equiv(result.return_expr, expected), (
        f"Expected If(c!=0, a+1, b+2), got {result.return_expr}"
    )
    print("PASS: test_encode_conditional_branch")


def test_encode_cast_sext():
    """sext i32 to i64 — identity in Int mode."""
    ir = """\
define i64 @ext(i32 %a) {
entry:
  %r = sext i32 %a to i64
  ret i64 %r
}
"""
    mod = parse_llvm_ir_string(ir)
    fn = mod.functions[0]
    result = encode_function(fn)

    a = z3.Int("%a")
    assert _z3_equiv(result.return_expr, a), (
        f"sext should be identity in Int mode, got {result.return_expr}"
    )
    print("PASS: test_encode_cast_sext")


def test_encode_cast_trunc():
    """trunc i64 to i32 — identity in Int mode."""
    ir = """\
define i32 @trn(i64 %a) {
entry:
  %r = trunc i64 %a to i32
  ret i32 %r
}
"""
    mod = parse_llvm_ir_string(ir)
    fn = mod.functions[0]
    result = encode_function(fn)

    a = z3.Int("%a")
    assert _z3_equiv(result.return_expr, a), (
        f"trunc should be identity in Int mode, got {result.return_expr}"
    )
    print("PASS: test_encode_cast_trunc")


def test_encode_io_model_output():
    """Call to @_ZNSolsEi records output."""
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
    result = encode_function(fn)

    assert len(result.outputs) == 1, f"expected 1 output, got {len(result.outputs)}"
    out = result.outputs[0]
    assert out.operand_type == "i32", f"type: {out.operand_type}"

    val = z3.Int("%val")
    assert _z3_equiv(out.expr, val), f"output expr: {out.expr}"
    print("PASS: test_encode_io_model_output")


def test_encode_io_model_input():
    """Call to @_ZNSirsERi creates fresh input."""
    ir = """\
declare ptr @_ZNSirsERi(ptr, ptr)
define void @read_int(ptr %is, ptr %x) {
entry:
  %r = call ptr @_ZNSirsERi(ptr %is, ptr %x)
  ret void
}
"""
    mod = parse_llvm_ir_string(ir)
    fn = mod.functions[0]
    result = encode_function(fn)

    assert len(result.inputs) == 1, f"expected 1 input, got {len(result.inputs)}"
    inp = result.inputs[0]
    assert inp.name == "input_0", f"name: {inp.name}"
    assert inp.bit_width == 32, f"bit_width: {inp.bit_width}"
    print("PASS: test_encode_io_model_input")


def test_encode_unsupported():
    """load/store marks unsupported."""
    ir = """\
define i32 @mem(ptr %p) {
entry:
  %v = load i32, ptr %p
  store i32 42, ptr %p
  ret i32 %v
}
"""
    mod = parse_llvm_ir_string(ir)
    fn = mod.functions[0]
    result = encode_function(fn)

    assert result.has_unsupported, "should be unsupported"
    assert "load" in result.unsupported_opcodes, f"opcodes: {result.unsupported_opcodes}"
    assert "store" in result.unsupported_opcodes, f"opcodes: {result.unsupported_opcodes}"
    print("PASS: test_encode_unsupported")


# ---------------------------------------------------------------------------
# Equivalence tests
# ---------------------------------------------------------------------------

def test_equiv_identical():
    """Same function twice -> EQUIVALENT."""
    ir = """\
define i32 @add(i32 %a, i32 %b) {
entry:
  %r = add i32 %a, %b
  ret i32 %r
}
"""
    mod = parse_llvm_ir_string(ir)
    fn = mod.functions[0]
    result = check_equivalence_functions(fn, fn)

    assert result.verdict == "EQUIVALENT", f"verdict: {result.verdict}"
    print("PASS: test_equiv_identical")


def test_equiv_different_ops():
    """add vs sub -> COUNTEREXAMPLE with concrete values."""
    ir_a = """\
define i32 @op(i32 %a, i32 %b) {
entry:
  %r = add i32 %a, %b
  ret i32 %r
}
"""
    ir_b = """\
define i32 @op(i32 %a, i32 %b) {
entry:
  %r = sub i32 %a, %b
  ret i32 %r
}
"""
    mod_a = parse_llvm_ir_string(ir_a)
    mod_b = parse_llvm_ir_string(ir_b)
    result = check_equivalence_functions(
        mod_a.functions[0], mod_b.functions[0]
    )

    assert result.verdict == "COUNTEREXAMPLE", f"verdict: {result.verdict}"
    assert result.counterexample is not None, "expected counterexample"
    print("PASS: test_equiv_different_ops")


def test_equiv_commutative():
    """add %a, %b vs add %b, %a -> EQUIVALENT."""
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
    result = check_equivalence_functions(
        mod_a.functions[0], mod_b.functions[0]
    )

    assert result.verdict == "EQUIVALENT", f"verdict: {result.verdict}"
    print("PASS: test_equiv_commutative")


def test_equiv_icmp_swap():
    """icmp slt %a, %b vs icmp sgt %b, %a -> EQUIVALENT."""
    ir_a = """\
define i32 @cmp(i32 %a, i32 %b) {
entry:
  %r = icmp slt i32 %a, %b
  ret i32 %r
}
"""
    ir_b = """\
define i32 @cmp(i32 %x, i32 %y) {
entry:
  %r = icmp sgt i32 %y, %x
  ret i32 %r
}
"""
    mod_a = parse_llvm_ir_string(ir_a)
    mod_b = parse_llvm_ir_string(ir_b)
    result = check_equivalence_functions(
        mod_a.functions[0], mod_b.functions[0]
    )

    assert result.verdict == "EQUIVALENT", f"verdict: {result.verdict}"
    print("PASS: test_equiv_icmp_swap")


def test_equiv_io_same():
    """read+add1+print vs same -> EQUIVALENT."""
    ir = """\
declare ptr @_ZNSirsERi(ptr, ptr)
declare ptr @_ZNSolsEi(ptr, i32)
define void @io(ptr %is, ptr %os, ptr %x) {
entry:
  %c1 = call ptr @_ZNSirsERi(ptr %is, ptr %x)
  %val = load i32, ptr %x
  %sum = add i32 %val, 1
  %c2 = call ptr @_ZNSolsEi(ptr %os, i32 %sum)
  ret void
}
"""
    mod = parse_llvm_ir_string(ir)
    fn = mod.functions[0]
    result = check_equivalence_functions(fn, fn)

    assert result.verdict == "EQUIVALENT", f"verdict: {result.verdict}"
    print("PASS: test_equiv_io_same")


def test_equiv_io_different():
    """read+add1+print vs read+add2+print -> COUNTEREXAMPLE."""
    ir_a = """\
declare ptr @_ZNSirsERi(ptr, ptr)
declare ptr @_ZNSolsEi(ptr, i32)
define void @io(ptr %is, ptr %os, ptr %x) {
entry:
  %c1 = call ptr @_ZNSirsERi(ptr %is, ptr %x)
  %val = load i32, ptr %x
  %sum = add i32 %val, 1
  %c2 = call ptr @_ZNSolsEi(ptr %os, i32 %sum)
  ret void
}
"""
    ir_b = """\
declare ptr @_ZNSirsERi(ptr, ptr)
declare ptr @_ZNSolsEi(ptr, i32)
define void @io(ptr %is, ptr %os, ptr %x) {
entry:
  %c1 = call ptr @_ZNSirsERi(ptr %is, ptr %x)
  %val = load i32, ptr %x
  %sum = add i32 %val, 2
  %c2 = call ptr @_ZNSolsEi(ptr %os, i32 %sum)
  ret void
}
"""
    mod_a = parse_llvm_ir_string(ir_a)
    mod_b = parse_llvm_ir_string(ir_b)
    result = check_equivalence_functions(
        mod_a.functions[0], mod_b.functions[0]
    )

    assert result.verdict == "COUNTEREXAMPLE", f"verdict: {result.verdict}"
    print("PASS: test_equiv_io_different")


def test_equiv_multiple_outputs():
    """Two outputs compared pairwise."""
    ir_a = """\
declare ptr @_ZNSolsEi(ptr, i32)
define void @multi(ptr %os, i32 %a, i32 %b) {
entry:
  %sum = add i32 %a, %b
  %c1 = call ptr @_ZNSolsEi(ptr %os, i32 %sum)
  %diff = sub i32 %a, %b
  %c2 = call ptr @_ZNSolsEi(ptr %os, i32 %diff)
  ret void
}
"""
    ir_b = """\
declare ptr @_ZNSolsEi(ptr, i32)
define void @multi(ptr %os, i32 %x, i32 %y) {
entry:
  %s = add i32 %y, %x
  %c1 = call ptr @_ZNSolsEi(ptr %os, i32 %s)
  %d = sub i32 %x, %y
  %c2 = call ptr @_ZNSolsEi(ptr %os, i32 %d)
  ret void
}
"""
    mod_a = parse_llvm_ir_string(ir_a)
    mod_b = parse_llvm_ir_string(ir_b)
    result = check_equivalence_functions(
        mod_a.functions[0], mod_b.functions[0]
    )

    assert result.verdict == "EQUIVALENT", f"verdict: {result.verdict}"
    print("PASS: test_equiv_multiple_outputs")


def test_equiv_return_value():
    """No I/O, compare return exprs: a+b vs b+a -> EQUIVALENT."""
    ir_a = """\
define i32 @sum(i32 %a, i32 %b) {
entry:
  %r = add i32 %a, %b
  ret i32 %r
}
"""
    ir_b = """\
define i32 @sum(i32 %x, i32 %y) {
entry:
  %r = add i32 %y, %x
  ret i32 %r
}
"""
    mod_a = parse_llvm_ir_string(ir_a)
    mod_b = parse_llvm_ir_string(ir_b)
    result = check_equivalence_functions(
        mod_a.functions[0], mod_b.functions[0]
    )

    assert result.verdict == "EQUIVALENT", f"verdict: {result.verdict}"
    print("PASS: test_equiv_return_value")


def test_equiv_simple_loop():
    """Loop in two identical versions -> EQUIVALENT (bounded)."""
    ir = """\
define i32 @loop_sum(i32 %n) {
entry:
  br label %header
header:
  %i = phi i32 [ 0, %entry ], [ %i.next, %body ]
  %sum = phi i32 [ 0, %entry ], [ %sum.next, %body ]
  %cond = icmp slt i32 %i, %n
  br i1 %cond, label %body, label %exit
body:
  %i.next = add i32 %i, 1
  %sum.next = add i32 %sum, %i.next
  br label %header
exit:
  ret i32 %sum
}
"""
    mod = parse_llvm_ir_string(ir)
    fn = mod.functions[0]
    result_a = encode_function(fn, loop_bound=5)
    result_b = encode_function(fn, loop_bound=5)

    assert result_a.loop_bound_hit, "should detect loop"
    assert result_b.loop_bound_hit, "should detect loop"

    equiv = check_equivalence(result_a, result_b)
    assert equiv.verdict == "EQUIVALENT", f"verdict: {equiv.verdict}"
    assert equiv.bounded, "should be bounded"
    print("PASS: test_equiv_simple_loop")


def test_equiv_custom_timeout():
    """Very short timeout — should handle gracefully."""
    # Build a problem with many multiplications that is hard to prove.
    lines_a = ["define i32 @hard(i32 %a, i32 %b, i32 %c) {", "entry:"]
    lines_b = ["define i32 @hard(i32 %x, i32 %y, i32 %z) {", "entry:"]
    prev_a, prev_b = "%a", "%x"
    for i in range(50):
        ca, cb = f"%t{i}", f"%u{i}"
        if i % 2 == 0:
            lines_a.append(f"  {ca} = mul i32 {prev_a}, %b")
            lines_b.append(f"  {cb} = mul i32 %y, {prev_b}")
        else:
            lines_a.append(f"  {ca} = add i32 {prev_a}, %c")
            lines_b.append(f"  {cb} = add i32 {prev_b}, %z")
        prev_a, prev_b = ca, cb
    lines_a += [f"  ret i32 {prev_a}", "}"]
    lines_b += [f"  ret i32 {prev_b}", "}"]
    ir_a = "\n".join(lines_a)
    ir_b = "\n".join(lines_b)

    mod_a = parse_llvm_ir_string(ir_a)
    mod_b = parse_llvm_ir_string(ir_b)
    result = check_equivalence_functions(
        mod_a.functions[0], mod_b.functions[0], timeout_ms=1
    )

    # With 1ms timeout, Z3 may return UNKNOWN or solve it; either is valid.
    assert result.verdict in ("UNKNOWN", "EQUIVALENT", "COUNTEREXAMPLE"), (
        f"Unexpected verdict: {result.verdict}"
    )
    print("PASS: test_equiv_custom_timeout")


if __name__ == "__main__":
    test_encode_simple_add()
    test_encode_icmp_predicates()
    test_encode_select()
    test_encode_phi_node()
    test_encode_conditional_branch()
    test_encode_cast_sext()
    test_encode_cast_trunc()
    test_encode_io_model_output()
    test_encode_io_model_input()
    test_encode_unsupported()
    test_equiv_identical()
    test_equiv_different_ops()
    test_equiv_commutative()
    test_equiv_icmp_swap()
    test_equiv_io_same()
    test_equiv_io_different()
    test_equiv_multiple_outputs()
    test_equiv_return_value()
    test_equiv_simple_loop()
    test_equiv_custom_timeout()
