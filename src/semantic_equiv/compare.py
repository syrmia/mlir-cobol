"""
Compare two parsed LLVM IR modules for semantic equivalence.

Provides alpha-equivalence checking (ignoring SSA name differences),
commutative operation handling, and comparison predicate swap recognition.
Reports detailed differences when modules diverge.
"""

from __future__ import annotations

import copy
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from semantic_equiv.ir_parser import (
    BasicBlock,
    Function,
    Instruction,
    Module,
    Operand,
    parse_llvm_ir,
    parse_llvm_ir_string,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_COMMUTATIVE_OPS = {"add", "mul", "and", "or", "xor", "fadd", "fmul"}

_PREDICATE_SWAPS = {
    "slt": "sgt", "sgt": "slt",
    "sle": "sge", "sge": "sle",
    "ult": "ugt", "ugt": "ult",
    "ule": "uge", "uge": "ule",
    "eq": "eq", "ne": "ne",
    "olt": "ogt", "ogt": "olt",
    "ole": "oge", "oge": "ole",
    "oeq": "oeq", "one": "one",
    "une": "une", "ueq": "ueq",
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Difference:
    """A single divergence point between two modules."""

    location: str
    kind: str
    detail_a: str
    detail_b: str

    def __str__(self) -> str:
        return f"{self.location}: {self.kind} — {self.detail_a!r} vs {self.detail_b!r}"


@dataclass
class ComparisonResult:
    """Top-level result of comparing two modules."""

    equivalent: bool
    differences: list[Difference] = field(default_factory=list)

    def summary(self) -> str:
        """Return a human-readable summary of the comparison."""
        if self.equivalent:
            return "Modules are semantically equivalent."
        lines = [f"Modules differ ({len(self.differences)} difference(s)):"]
        for d in self.differences:
            lines.append(f"  - {d}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Alpha-equivalence map
# ---------------------------------------------------------------------------

class _AlphaMap:
    """Bidirectional mapping between SSA names in two modules."""

    def __init__(self) -> None:
        self.map_a_to_b: dict[str, str] = {}
        self.map_b_to_a: dict[str, str] = {}

    def copy(self) -> _AlphaMap:
        """Return a shallow copy of this map."""
        new = _AlphaMap()
        new.map_a_to_b = dict(self.map_a_to_b)
        new.map_b_to_a = dict(self.map_b_to_a)
        return new

    def bind(self, name_a: str, name_b: str) -> bool:
        """Record a new binding.  Return False if there is a conflict."""
        existing_b = self.map_a_to_b.get(name_a)
        existing_a = self.map_b_to_a.get(name_b)
        if existing_b is not None and existing_b != name_b:
            return False
        if existing_a is not None and existing_a != name_a:
            return False
        self.map_a_to_b[name_a] = name_b
        self.map_b_to_a[name_b] = name_a
        return True

    def lookup_a(self, name_a: str) -> str | None:
        """Get the B-side name for *name_a*."""
        return self.map_a_to_b.get(name_a)

    def lookup_b(self, name_b: str) -> str | None:
        """Get the A-side name for *name_b*."""
        return self.map_b_to_a.get(name_b)

    def check(self, name_a: str, name_b: str) -> bool:
        """Return True if names are compatible (mapped to each other or both free)."""
        existing_b = self.map_a_to_b.get(name_a)
        existing_a = self.map_b_to_a.get(name_b)
        if existing_b is not None:
            return existing_b == name_b
        if existing_a is not None:
            return existing_a == name_a
        return True


# ---------------------------------------------------------------------------
# Operand comparison
# ---------------------------------------------------------------------------

def _compare_operands(op_a: Operand, op_b: Operand, alpha_map: _AlphaMap) -> bool:
    """Check whether two operands are equivalent under *alpha_map*."""
    # Compare types if both present.
    if op_a.type and op_b.type:
        if op_a.type.raw != op_b.type.raw:
            return False

    name_a = op_a.name
    name_b = op_b.name

    if name_a.startswith("%") and name_b.startswith("%"):
        # SSA local names — check via alpha map.
        if alpha_map.check(name_a, name_b):
            alpha_map.bind(name_a, name_b)
            return True
        return False

    if name_a.startswith("@") and name_b.startswith("@"):
        # Global names — must match literally.
        return name_a == name_b

    # Constants (integers, floats, etc.) — compare literally.
    return name_a == name_b


def _operands_match(ops_a: list[Operand], ops_b: list[Operand],
                    alpha_map: _AlphaMap) -> bool:
    """Check whether two operand lists match positionally."""
    if len(ops_a) != len(ops_b):
        return False
    for a, b in zip(ops_a, ops_b):
        if not _compare_operands(a, b, alpha_map):
            return False
    return True


# ---------------------------------------------------------------------------
# Label comparison
# ---------------------------------------------------------------------------

def _compare_labels(label_a: str, label_b: str, alpha_map: _AlphaMap) -> bool:
    """Compare two block labels through the alpha map.

    Labels are prefixed with ``%`` for lookup in the same namespace as SSA
    values.
    """
    key_a = label_a if label_a.startswith("%") else f"%{label_a}"
    key_b = label_b if label_b.startswith("%") else f"%{label_b}"
    if alpha_map.check(key_a, key_b):
        alpha_map.bind(key_a, key_b)
        return True
    return False


# ---------------------------------------------------------------------------
# Instruction comparison
# ---------------------------------------------------------------------------

def _compare_instructions(inst_a: Instruction, inst_b: Instruction,
                          alpha_map: _AlphaMap, diffs: list[Difference],
                          loc: str) -> None:
    """Compare two instructions, appending differences to *diffs*."""
    # Opcode.
    if inst_a.opcode != inst_b.opcode:
        diffs.append(Difference(loc, "opcode_mismatch",
                                inst_a.opcode, inst_b.opcode))
        return

    opcode = inst_a.opcode

    # Result type.
    if inst_a.result_type and inst_b.result_type:
        if inst_a.result_type.raw != inst_b.result_type.raw:
            diffs.append(Difference(loc, "type_mismatch",
                                    inst_a.result_type.raw,
                                    inst_b.result_type.raw))
            return

    # Bind result names.
    if inst_a.result and inst_b.result:
        if not alpha_map.bind(inst_a.result, inst_b.result):
            diffs.append(Difference(loc, "operand_mismatch",
                                    inst_a.result, inst_b.result))
            return

    # -- Dispatch by opcode ------------------------------------------------

    if opcode in ("icmp", "fcmp"):
        _compare_cmp(inst_a, inst_b, alpha_map, diffs, loc)
        return

    if opcode == "br":
        _compare_br(inst_a, inst_b, alpha_map, diffs, loc)
        return

    if opcode == "call":
        _compare_call(inst_a, inst_b, alpha_map, diffs, loc)
        return

    if opcode == "phi":
        _compare_phi(inst_a, inst_b, alpha_map, diffs, loc)
        return

    if opcode == "select":
        _compare_select(inst_a, inst_b, alpha_map, diffs, loc)
        return

    if opcode == "ret":
        _compare_ret(inst_a, inst_b, alpha_map, diffs, loc)
        return

    # Binary ops (with commutative fallback).
    if opcode in _COMMUTATIVE_OPS:
        _compare_binary_commutative(inst_a, inst_b, alpha_map, diffs, loc)
        return

    # Default: positional operand comparison.
    _compare_operands_default(inst_a, inst_b, alpha_map, diffs, loc)


def _compare_binary_commutative(inst_a: Instruction, inst_b: Instruction,
                                alpha_map: _AlphaMap, diffs: list[Difference],
                                loc: str) -> None:
    """Compare a commutative binary op, trying both orderings."""
    if len(inst_a.operands) == 2 and len(inst_b.operands) == 2:
        # Try normal order first.
        saved = alpha_map.copy()
        if _operands_match(inst_a.operands, inst_b.operands, alpha_map):
            return
        # Restore and try swapped.
        alpha_map.map_a_to_b = saved.map_a_to_b
        alpha_map.map_b_to_a = saved.map_b_to_a
        swapped = [inst_b.operands[1], inst_b.operands[0]]
        if _operands_match(inst_a.operands, swapped, alpha_map):
            return
        # Both failed.
        diffs.append(Difference(
            loc, "operand_mismatch",
            f"{inst_a.operands[0].name}, {inst_a.operands[1].name}",
            f"{inst_b.operands[0].name}, {inst_b.operands[1].name}",
        ))
    else:
        _compare_operands_default(inst_a, inst_b, alpha_map, diffs, loc)


def _compare_cmp(inst_a: Instruction, inst_b: Instruction,
                 alpha_map: _AlphaMap, diffs: list[Difference],
                 loc: str) -> None:
    """Compare icmp/fcmp, allowing predicate swaps."""
    pred_a = inst_a.predicate or ""
    pred_b = inst_b.predicate or ""

    if pred_a == pred_b:
        # Same predicate — compare operands normally.
        if not _operands_match(inst_a.operands, inst_b.operands, alpha_map):
            diffs.append(Difference(
                loc, "operand_mismatch",
                ", ".join(o.name for o in inst_a.operands),
                ", ".join(o.name for o in inst_b.operands),
            ))
        return

    # Try predicate swap: pred_a == swap(pred_b) with reversed operands.
    swapped_pred = _PREDICATE_SWAPS.get(pred_b)
    if swapped_pred == pred_a and len(inst_b.operands) == 2:
        reversed_ops = [inst_b.operands[1], inst_b.operands[0]]
        if _operands_match(inst_a.operands, reversed_ops, alpha_map):
            return

    diffs.append(Difference(loc, "predicate_mismatch", pred_a, pred_b))


def _compare_br(inst_a: Instruction, inst_b: Instruction,
                alpha_map: _AlphaMap, diffs: list[Difference],
                loc: str) -> None:
    """Compare branch instructions."""
    # Unconditional.
    if inst_a.dest_label and inst_b.dest_label:
        if not _compare_labels(inst_a.dest_label, inst_b.dest_label, alpha_map):
            diffs.append(Difference(loc, "operand_mismatch",
                                    inst_a.dest_label, inst_b.dest_label))
        return

    # Conditional.
    if inst_a.condition and inst_b.condition:
        if not _compare_operands(inst_a.condition, inst_b.condition, alpha_map):
            diffs.append(Difference(loc, "operand_mismatch",
                                    inst_a.condition.name, inst_b.condition.name))
            return
        if inst_a.true_label and inst_b.true_label:
            if not _compare_labels(inst_a.true_label, inst_b.true_label, alpha_map):
                diffs.append(Difference(loc, "operand_mismatch",
                                        inst_a.true_label, inst_b.true_label))
        if inst_a.false_label and inst_b.false_label:
            if not _compare_labels(inst_a.false_label, inst_b.false_label, alpha_map):
                diffs.append(Difference(loc, "operand_mismatch",
                                        inst_a.false_label, inst_b.false_label))
        return

    # Mismatch in branch type.
    diffs.append(Difference(loc, "operand_mismatch",
                            inst_a.raw, inst_b.raw))


def _compare_call(inst_a: Instruction, inst_b: Instruction,
                  alpha_map: _AlphaMap, diffs: list[Difference],
                  loc: str) -> None:
    """Compare call instructions."""
    callee_a = inst_a.callee or ""
    callee_b = inst_b.callee or ""
    if callee_a != callee_b:
        diffs.append(Difference(loc, "callee_mismatch", callee_a, callee_b))
        return

    if len(inst_a.call_args) != len(inst_b.call_args):
        diffs.append(Difference(loc, "operand_mismatch",
                                str(len(inst_a.call_args)),
                                str(len(inst_b.call_args))))
        return

    for i, (arg_a, arg_b) in enumerate(zip(inst_a.call_args, inst_b.call_args)):
        if not _compare_operands(arg_a, arg_b, alpha_map):
            diffs.append(Difference(loc, "operand_mismatch",
                                    arg_a.name, arg_b.name))
            return


def _compare_phi(inst_a: Instruction, inst_b: Instruction,
                 alpha_map: _AlphaMap, diffs: list[Difference],
                 loc: str) -> None:
    """Compare phi instructions, allowing reordering of incoming pairs."""
    if len(inst_a.phi_incoming) != len(inst_b.phi_incoming):
        diffs.append(Difference(loc, "operand_mismatch",
                                str(len(inst_a.phi_incoming)),
                                str(len(inst_b.phi_incoming))))
        return

    # Try to match each incoming pair from A to a pair in B.
    used: set[int] = set()
    for val_a, label_a in inst_a.phi_incoming:
        found = False
        for j, (val_b, label_b) in enumerate(inst_b.phi_incoming):
            if j in used:
                continue
            saved = alpha_map.copy()
            op_a = Operand(name=val_a)
            op_b = Operand(name=val_b)
            if (_compare_operands(op_a, op_b, saved)
                    and _compare_labels(label_a, label_b, saved)):
                # Commit the bindings.
                alpha_map.map_a_to_b = saved.map_a_to_b
                alpha_map.map_b_to_a = saved.map_b_to_a
                used.add(j)
                found = True
                break
        if not found:
            diffs.append(Difference(
                loc, "operand_mismatch",
                f"[{val_a}, {label_a}]",
                "no matching incoming pair",
            ))
            return


def _compare_select(inst_a: Instruction, inst_b: Instruction,
                    alpha_map: _AlphaMap, diffs: list[Difference],
                    loc: str) -> None:
    """Compare select instructions."""
    if inst_a.condition and inst_b.condition:
        if not _compare_operands(inst_a.condition, inst_b.condition, alpha_map):
            diffs.append(Difference(loc, "operand_mismatch",
                                    inst_a.condition.name,
                                    inst_b.condition.name))
            return
    if inst_a.true_value and inst_b.true_value:
        if not _compare_operands(inst_a.true_value, inst_b.true_value, alpha_map):
            diffs.append(Difference(loc, "operand_mismatch",
                                    inst_a.true_value.name,
                                    inst_b.true_value.name))
            return
    if inst_a.false_value and inst_b.false_value:
        if not _compare_operands(inst_a.false_value, inst_b.false_value, alpha_map):
            diffs.append(Difference(loc, "operand_mismatch",
                                    inst_a.false_value.name,
                                    inst_b.false_value.name))
            return


def _compare_ret(inst_a: Instruction, inst_b: Instruction,
                 alpha_map: _AlphaMap, diffs: list[Difference],
                 loc: str) -> None:
    """Compare return instructions."""
    if not _operands_match(inst_a.operands, inst_b.operands, alpha_map):
        a_str = inst_a.operands[0].name if inst_a.operands else "void"
        b_str = inst_b.operands[0].name if inst_b.operands else "void"
        diffs.append(Difference(loc, "operand_mismatch", a_str, b_str))


def _compare_operands_default(inst_a: Instruction, inst_b: Instruction,
                              alpha_map: _AlphaMap, diffs: list[Difference],
                              loc: str) -> None:
    """Default positional operand comparison."""
    if not _operands_match(inst_a.operands, inst_b.operands, alpha_map):
        a_str = ", ".join(o.name for o in inst_a.operands)
        b_str = ", ".join(o.name for o in inst_b.operands)
        diffs.append(Difference(loc, "operand_mismatch", a_str, b_str))


# ---------------------------------------------------------------------------
# Block comparison
# ---------------------------------------------------------------------------

def _compare_blocks(block_a: BasicBlock, block_b: BasicBlock,
                    alpha_map: _AlphaMap, diffs: list[Difference],
                    loc: str) -> None:
    """Compare two basic blocks instruction-by-instruction."""
    # Bind block labels.
    key_a = f"%{block_a.label}" if not block_a.label.startswith("%") else block_a.label
    key_b = f"%{block_b.label}" if not block_b.label.startswith("%") else block_b.label
    alpha_map.bind(key_a, key_b)

    if len(block_a.instructions) != len(block_b.instructions):
        diffs.append(Difference(loc, "instruction_count",
                                str(len(block_a.instructions)),
                                str(len(block_b.instructions))))
        return

    for i, (ia, ib) in enumerate(zip(block_a.instructions, block_b.instructions)):
        inst_loc = f"{loc} > instruction {i}"
        _compare_instructions(ia, ib, alpha_map, diffs, inst_loc)


# ---------------------------------------------------------------------------
# Function comparison
# ---------------------------------------------------------------------------

def _compare_functions(fn_a: Function, fn_b: Function,
                       diffs: list[Difference], loc: str) -> None:
    """Compare two functions structurally."""
    # Return type.
    if fn_a.return_type.raw != fn_b.return_type.raw:
        diffs.append(Difference(loc, "return_type",
                                fn_a.return_type.raw, fn_b.return_type.raw))
        return

    # Parameter count.
    if len(fn_a.params) != len(fn_b.params):
        diffs.append(Difference(loc, "param_count",
                                str(len(fn_a.params)), str(len(fn_b.params))))
        return

    # Parameter types.
    for i, (pa, pb) in enumerate(zip(fn_a.params, fn_b.params)):
        if pa.type.raw != pb.type.raw:
            diffs.append(Difference(f"{loc} > param {i}", "type_mismatch",
                                    pa.type.raw, pb.type.raw))
            return

    # Create alpha map and bind parameter names.
    alpha_map = _AlphaMap()
    for pa, pb in zip(fn_a.params, fn_b.params):
        if pa.name and pb.name:
            alpha_map.bind(pa.name, pb.name)

    # Block count.
    if len(fn_a.blocks) != len(fn_b.blocks):
        diffs.append(Difference(loc, "block_count",
                                str(len(fn_a.blocks)), str(len(fn_b.blocks))))
        return

    # Compare blocks by position.
    for i, (ba, bb) in enumerate(zip(fn_a.blocks, fn_b.blocks)):
        block_loc = f"{loc} > block {i}"
        _compare_blocks(ba, bb, alpha_map, diffs, block_loc)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compare_modules(mod_a: Module, mod_b: Module) -> ComparisonResult:
    """Compare two parsed LLVM IR modules for semantic equivalence."""
    diffs: list[Difference] = []

    # Build function name sets (definitions only, skip declarations).
    names_a = {fn.name for fn in mod_a.functions}
    names_b = {fn.name for fn in mod_b.functions}

    for name in sorted(names_a - names_b):
        diffs.append(Difference(name, "missing_function",
                                name, "(not present)"))
    for name in sorted(names_b - names_a):
        diffs.append(Difference(name, "missing_function",
                                "(not present)", name))

    # Compare matched functions.
    for name in sorted(names_a & names_b):
        fn_a = mod_a.get_function(name)
        fn_b = mod_b.get_function(name)
        if fn_a and fn_b:
            _compare_functions(fn_a, fn_b, diffs, name)

    return ComparisonResult(equivalent=len(diffs) == 0, differences=diffs)


def compare_functions(fn_a: Function, fn_b: Function) -> ComparisonResult:
    """Compare two individual functions for semantic equivalence."""
    diffs: list[Difference] = []
    loc = fn_a.name or fn_b.name or "<function>"
    _compare_functions(fn_a, fn_b, diffs, loc)
    return ComparisonResult(equivalent=len(diffs) == 0, differences=diffs)


def compare_cpp_files(
    file_a: str | Path,
    file_b: str | Path,
    function_name: str | None = None,
    clang_path: str | Path | None = None,
    opt_path: str | Path | None = None,
) -> ComparisonResult:
    """End-to-end comparison: normalize two C++ files and compare their IR.

    If *function_name* is given, only that function is compared.
    """
    from semantic_equiv.normalize import normalize_cpp

    file_a = Path(file_a)
    file_b = Path(file_b)

    with tempfile.TemporaryDirectory(prefix="semantic_cmp_") as tmpdir:
        norm_a = normalize_cpp(file_a, output_dir=Path(tmpdir) / "a",
                               clang_path=clang_path, opt_path=opt_path)
        norm_b = normalize_cpp(file_b, output_dir=Path(tmpdir) / "b",
                               clang_path=clang_path, opt_path=opt_path)

        mod_a = parse_llvm_ir(norm_a)
        mod_b = parse_llvm_ir(norm_b)

    if function_name:
        # Compare a single function.
        fn_name = function_name if function_name.startswith("@") else f"@{function_name}"
        fn_a = mod_a.get_function(fn_name)
        fn_b = mod_b.get_function(fn_name)
        if fn_a is None and fn_b is None:
            return ComparisonResult(
                equivalent=False,
                differences=[Difference(fn_name, "missing_function",
                                        "(not found)", "(not found)")],
            )
        if fn_a is None:
            return ComparisonResult(
                equivalent=False,
                differences=[Difference(fn_name, "missing_function",
                                        "(not present)", fn_name)],
            )
        if fn_b is None:
            return ComparisonResult(
                equivalent=False,
                differences=[Difference(fn_name, "missing_function",
                                        fn_name, "(not present)")],
            )
        return compare_functions(fn_a, fn_b)

    return compare_modules(mod_a, mod_b)
