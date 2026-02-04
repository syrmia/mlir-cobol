#!/usr/bin/env python3
"""Tests for semantic_equiv.ir_parser."""

import sys
from pathlib import Path

# Ensure src/ is importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from semantic_equiv.ir_parser import (
    IRParseError,
    LLType,
    Module,
    parse_llvm_ir_string,
)


def test_empty_module():
    """An empty string should produce an empty module."""
    mod = parse_llvm_ir_string("")
    assert isinstance(mod, Module)
    assert mod.functions == []
    assert mod.globals == []
    print("PASS: test_empty_module")


def test_module_metadata():
    """Module-level metadata should be parsed."""
    ir = """\
source_filename = "test.cpp"
target datalayout = "e-m:o-i64:64"
target triple = "x86_64-apple-macosx"
"""
    mod = parse_llvm_ir_string(ir)
    assert mod.source_filename == "test.cpp"
    assert mod.target_datalayout == "e-m:o-i64:64"
    assert mod.target_triple == "x86_64-apple-macosx"
    print("PASS: test_module_metadata")


def test_simple_function():
    """A function returning void should be parsed."""
    ir = """\
define void @foo() {
entry:
  ret void
}
"""
    mod = parse_llvm_ir_string(ir)
    assert len(mod.functions) == 1
    fn = mod.functions[0]
    assert fn.name == "@foo"
    assert fn.return_type.is_void
    assert len(fn.blocks) == 1
    assert fn.blocks[0].label == "entry"
    assert fn.blocks[0].instructions[0].opcode == "ret"
    print("PASS: test_simple_function")


def test_arithmetic():
    """Binary arithmetic instructions should be parsed."""
    ir = """\
define i32 @add_nums(i32 %a, i32 %b) {
entry:
  %sum = add nsw i32 %a, %b
  ret i32 %sum
}
"""
    mod = parse_llvm_ir_string(ir)
    fn = mod.functions[0]
    assert fn.name == "@add_nums"
    assert len(fn.params) == 2
    assert fn.params[0].name == "%a"
    assert fn.params[1].name == "%b"

    add_inst = fn.blocks[0].instructions[0]
    assert add_inst.opcode == "add"
    assert add_inst.result == "%sum"
    assert add_inst.result_type.raw == "i32"
    assert len(add_inst.operands) == 2
    assert add_inst.operands[0].name == "%a"
    assert add_inst.operands[1].name == "%b"
    assert "nsw" in add_inst.flags
    print("PASS: test_arithmetic")


def test_branch():
    """Conditional and unconditional branches should be parsed."""
    ir = """\
define void @branch_test(i1 %cond) {
entry:
  br i1 %cond, label %then, label %else
then:
  br label %end
else:
  br label %end
end:
  ret void
}
"""
    mod = parse_llvm_ir_string(ir)
    fn = mod.functions[0]
    blocks = {b.label: b for b in fn.blocks}

    # Conditional branch
    br_cond = blocks["entry"].instructions[0]
    assert br_cond.opcode == "br"
    assert br_cond.condition is not None
    assert br_cond.condition.name == "%cond"
    assert br_cond.true_label == "%then"
    assert br_cond.false_label == "%else"

    # Unconditional branch
    br_uncond = blocks["then"].instructions[0]
    assert br_uncond.opcode == "br"
    assert br_uncond.dest_label == "%end"
    print("PASS: test_branch")


def test_call():
    """Call instructions should extract callee and args."""
    ir = """\
declare i32 @bar(i32, i32)

define i32 @caller() {
entry:
  %r = call i32 @bar(i32 10, i32 20)
  ret i32 %r
}
"""
    mod = parse_llvm_ir_string(ir)
    assert len(mod.declarations) == 1
    assert mod.declarations[0].name == "@bar"

    fn = mod.functions[0]
    call_inst = fn.blocks[0].instructions[0]
    assert call_inst.opcode == "call"
    assert call_inst.callee == "@bar"
    assert len(call_inst.call_args) == 2
    assert call_inst.call_args[0].name == "10"
    assert call_inst.call_args[1].name == "20"
    print("PASS: test_call")


def test_phi():
    """PHI nodes should capture incoming values and labels."""
    ir = """\
define i32 @phi_test(i1 %cond) {
entry:
  br i1 %cond, label %left, label %right
left:
  br label %merge
right:
  br label %merge
merge:
  %val = phi i32 [ 1, %left ], [ 2, %right ]
  ret i32 %val
}
"""
    mod = parse_llvm_ir_string(ir)
    fn = mod.functions[0]
    blocks = {b.label: b for b in fn.blocks}
    phi = blocks["merge"].instructions[0]
    assert phi.opcode == "phi"
    assert phi.result == "%val"
    assert phi.result_type.raw == "i32"
    assert len(phi.phi_incoming) == 2
    assert phi.phi_incoming[0] == ("1", "%left")
    assert phi.phi_incoming[1] == ("2", "%right")
    print("PASS: test_phi")


def test_global():
    """Global variables should be parsed."""
    ir = """\
@msg = private constant [6 x i8] c"hello\\00"
@counter = global i32 0
"""
    mod = parse_llvm_ir_string(ir)
    assert len(mod.globals) == 2
    assert mod.globals[0].name == "@msg"
    assert mod.globals[0].is_constant
    assert mod.globals[0].linkage == "private"
    assert mod.globals[1].name == "@counter"
    assert not mod.globals[1].is_constant
    print("PASS: test_global")


def test_icmp():
    """icmp instruction should capture predicate and operands."""
    ir = """\
define i1 @cmp(i32 %a, i32 %b) {
entry:
  %r = icmp slt i32 %a, %b
  ret i1 %r
}
"""
    mod = parse_llvm_ir_string(ir)
    fn = mod.functions[0]
    cmp = fn.blocks[0].instructions[0]
    assert cmp.opcode == "icmp"
    assert cmp.predicate == "slt"
    assert cmp.result == "%r"
    assert cmp.result_type.raw == "i1"
    assert len(cmp.operands) == 2
    print("PASS: test_icmp")


def test_select():
    """select instruction should capture condition and values."""
    ir = """\
define i32 @sel(i1 %c, i32 %a, i32 %b) {
entry:
  %r = select i1 %c, i32 %a, i32 %b
  ret i32 %r
}
"""
    mod = parse_llvm_ir_string(ir)
    fn = mod.functions[0]
    sel = fn.blocks[0].instructions[0]
    assert sel.opcode == "select"
    assert sel.condition.name == "%c"
    assert sel.true_value.name == "%a"
    assert sel.false_value.name == "%b"
    print("PASS: test_select")


def test_cast():
    """Cast instructions should parse source and dest types."""
    ir = """\
define i64 @cast_test(i32 %x) {
entry:
  %r = sext i32 %x to i64
  ret i64 %r
}
"""
    mod = parse_llvm_ir_string(ir)
    fn = mod.functions[0]
    cast = fn.blocks[0].instructions[0]
    assert cast.opcode == "sext"
    assert cast.result_type.raw == "i64"
    assert cast.operands[0].name == "%x"
    assert cast.operands[0].type.raw == "i32"
    print("PASS: test_cast")


def test_type_properties():
    """LLType properties should work correctly."""
    assert LLType("i32").is_integer
    assert LLType("i32").bit_width == 32
    assert not LLType("i32").is_void
    assert not LLType("i32").is_pointer
    assert not LLType("i32").is_float

    assert LLType("void").is_void
    assert LLType("ptr").is_pointer
    assert LLType("float").is_float
    assert LLType("double").is_float
    print("PASS: test_type_properties")


def test_get_function():
    """Module.get_function should find functions by name."""
    ir = """\
define void @foo() {
entry:
  ret void
}

define i32 @bar() {
entry:
  ret i32 0
}
"""
    mod = parse_llvm_ir_string(ir)
    assert mod.get_function("@foo") is not None
    assert mod.get_function("@bar") is not None
    assert mod.get_function("@baz") is None
    print("PASS: test_get_function")


def test_store_load():
    """Store and load instructions should be parsed."""
    ir = """\
define i32 @sl() {
entry:
  %p = alloca i32
  store i32 42, ptr %p
  %v = load i32, ptr %p
  ret i32 %v
}
"""
    mod = parse_llvm_ir_string(ir)
    fn = mod.functions[0]
    instrs = fn.blocks[0].instructions

    assert instrs[0].opcode == "alloca"
    assert instrs[1].opcode == "store"
    assert instrs[1].operands[0].name == "42"
    assert instrs[1].operands[1].name == "%p"
    assert instrs[2].opcode == "load"
    assert instrs[2].result == "%v"
    assert instrs[2].operands[0].name == "%p"
    print("PASS: test_store_load")


if __name__ == "__main__":
    test_empty_module()
    test_module_metadata()
    test_simple_function()
    test_arithmetic()
    test_branch()
    test_call()
    test_phi()
    test_global()
    test_icmp()
    test_select()
    test_cast()
    test_type_properties()
    test_get_function()
    test_store_load()
