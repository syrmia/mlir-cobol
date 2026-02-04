"""
Z3 symbolic encoding for LLVM IR semantic equivalence checking.

Encodes parsed LLVM IR into Z3 formulas, models cin/cout as symbolic I/O,
handles control flow via path conditions, supports loop unrolling to bound K,
and checks semantic equivalence between two encoded functions.
"""

from __future__ import annotations

import tempfile
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import z3

from semantic_equiv.ir_parser import (
    BasicBlock,
    Function,
    Instruction,
    LLType,
    Module,
    Operand,
    Parameter,
    parse_llvm_ir,
    parse_llvm_ir_string,
)
from semantic_equiv.fingerprint import (
    _OUTPUT_PATTERNS,
    _INPUT_PATTERNS,
    _IO_SKIP_PATTERNS,
    _classify_io_call,
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class SymbolicInput:
    """A symbolic input variable representing a cin read."""

    name: str              # "input_0", "input_1", ...
    z3_var: z3.ExprRef     # z3.Int("input_0") or z3.BitVec(...)
    bit_width: int         # from LLType (32, 64, etc.)


@dataclass
class SymbolicOutput:
    """A symbolic output expression representing a cout write."""

    expr: z3.ExprRef       # Z3 expression over symbolic inputs
    operand_type: str      # "i32", "i64", etc.


@dataclass
class EncodingResult:
    """Result of encoding a function into Z3 formulas."""

    function_name: str
    inputs: list[SymbolicInput]
    outputs: list[SymbolicOutput]
    return_expr: z3.ExprRef | None
    param_vars: list[z3.ExprRef]
    has_unsupported: bool
    unsupported_opcodes: set[str]
    loop_unroll_bound: int
    loop_bound_hit: bool


@dataclass
class EquivalenceResult:
    """Result of checking equivalence between two encoded functions."""

    verdict: str           # "EQUIVALENT" | "COUNTEREXAMPLE" | "UNKNOWN"
    counterexample: dict[str, int] | None
    details: str
    bounded: bool          # True if loops were unrolled
    loop_bound: int


# ---------------------------------------------------------------------------
# Z3Encoder
# ---------------------------------------------------------------------------

class Z3Encoder:
    """Encode parsed LLVM IR functions into Z3 formulas."""

    def __init__(self, *, loop_bound: int = 10, use_bitvec: bool = False):
        self._loop_bound = loop_bound
        self._use_bitvec = use_bitvec
        self._reset()

    def _reset(self) -> None:
        """Reset all mutable state for a fresh encoding."""
        self._env: dict[str, z3.ExprRef] = {}
        self._block_path_cond: dict[str, z3.BoolRef] = {}
        self._inputs: list[SymbolicInput] = []
        self._outputs: list[SymbolicOutput] = []
        self._return_expr: z3.ExprRef | None = None
        self._param_vars: list[z3.ExprRef] = []
        self._has_unsupported = False
        self._unsupported_opcodes: set[str] = set()
        self._loop_bound_hit = False
        self._input_counter = 0
        self._fresh_counter = 0

    # -- Variable helpers ---------------------------------------------------

    def _make_z3_var(self, name: str, ll_type: LLType | None) -> z3.ExprRef:
        """Create a Z3 variable (Int or BitVec) from a name and type."""
        if self._use_bitvec and ll_type and ll_type.bit_width:
            return z3.BitVec(name, ll_type.bit_width)
        return z3.Int(name)

    def _make_z3_const(
        self, value_str: str, ll_type: LLType | None
    ) -> z3.ExprRef:
        """Parse a numeric constant string into a Z3 expression."""
        value_str = value_str.strip()

        if value_str == "true":
            if self._use_bitvec and ll_type and ll_type.bit_width:
                return z3.BitVecVal(1, ll_type.bit_width)
            return z3.IntVal(1)
        if value_str == "false":
            if self._use_bitvec and ll_type and ll_type.bit_width:
                return z3.BitVecVal(0, ll_type.bit_width)
            return z3.IntVal(0)
        if value_str == "null" or value_str == "undef":
            if self._use_bitvec and ll_type and ll_type.bit_width:
                return z3.BitVecVal(0, ll_type.bit_width)
            return z3.IntVal(0)

        try:
            val = int(value_str)
        except ValueError:
            return self._fresh_var(ll_type)

        if self._use_bitvec and ll_type and ll_type.bit_width:
            return z3.BitVecVal(val, ll_type.bit_width)
        return z3.IntVal(val)

    def _resolve_operand(self, operand: Operand) -> z3.ExprRef:
        """Resolve an operand to a Z3 expression."""
        name = operand.name
        if name in self._env:
            return self._env[name]
        if name.startswith("%"):
            var = self._make_z3_var(name, operand.type)
            self._env[name] = var
            return var
        if name.startswith("@"):
            var = self._make_z3_var(name, operand.type)
            self._env[name] = var
            return var
        return self._make_z3_const(name, operand.type)

    def _fresh_input(self, bit_width: int = 32) -> z3.ExprRef:
        """Create a fresh symbolic input variable (for cin reads)."""
        name = f"input_{self._input_counter}"
        self._input_counter += 1
        ll_type = LLType(f"i{bit_width}")
        var = self._make_z3_var(name, ll_type)
        self._inputs.append(
            SymbolicInput(name=name, z3_var=var, bit_width=bit_width)
        )
        return var

    def _fresh_var(self, ll_type: LLType | None = None) -> z3.ExprRef:
        """Create a fresh unconstrained symbolic variable."""
        name = f"_fresh_{self._fresh_counter}"
        self._fresh_counter += 1
        return self._make_z3_var(name, ll_type)

    def _to_bool(self, expr: z3.ExprRef) -> z3.BoolRef:
        """Convert an integer/bitvec expression to a Z3 Bool."""
        if z3.is_bool(expr):
            return expr
        if z3.is_bv(expr):
            return expr != z3.BitVecVal(0, expr.sort().size())
        return expr != z3.IntVal(0)

    def _from_bool(self, expr: z3.BoolRef) -> z3.ExprRef:
        """Convert a Z3 Bool to Int/BitVec (True=1, False=0)."""
        if not z3.is_bool(expr):
            return expr
        if self._use_bitvec:
            return z3.If(expr, z3.BitVecVal(1, 32), z3.BitVecVal(0, 32))
        return z3.If(expr, z3.IntVal(1), z3.IntVal(0))

    # -- Instruction encoders -----------------------------------------------

    def _encode_arithmetic(self, inst: Instruction) -> None:
        """Encode add, sub, mul, sdiv, udiv, srem, urem."""
        if len(inst.operands) < 2 or inst.result is None:
            return
        a = self._resolve_operand(inst.operands[0])
        b = self._resolve_operand(inst.operands[1])

        ops = {
            "add": lambda: a + b,
            "sub": lambda: a - b,
            "mul": lambda: a * b,
            "sdiv": lambda: a / b,
            "udiv": lambda: z3.UDiv(a, b) if z3.is_bv(a) else a / b,
            "srem": lambda: a % b,
            "urem": lambda: z3.URem(a, b) if z3.is_bv(a) else a % b,
        }

        op_fn = ops.get(inst.opcode)
        if op_fn:
            self._env[inst.result] = op_fn()

    def _encode_bitwise(self, inst: Instruction) -> None:
        """Encode and, or, xor, shl, lshr, ashr."""
        if len(inst.operands) < 2 or inst.result is None:
            return

        if not self._use_bitvec:
            self._has_unsupported = True
            self._unsupported_opcodes.add(inst.opcode)
            self._env[inst.result] = self._fresh_var(inst.result_type)
            return

        a = self._resolve_operand(inst.operands[0])
        b = self._resolve_operand(inst.operands[1])

        ops = {
            "and": lambda: a & b,
            "or": lambda: a | b,
            "xor": lambda: a ^ b,
            "shl": lambda: a << b,
            "lshr": lambda: z3.LShR(a, b),
            "ashr": lambda: a >> b,
        }

        op_fn = ops.get(inst.opcode)
        if op_fn:
            self._env[inst.result] = op_fn()

    def _encode_icmp(self, inst: Instruction) -> None:
        """Encode icmp with all predicates."""
        if len(inst.operands) < 2 or inst.result is None:
            return
        a = self._resolve_operand(inst.operands[0])
        b = self._resolve_operand(inst.operands[1])
        pred = inst.predicate or "eq"

        if self._use_bitvec:
            pred_map = {
                "eq": lambda: a == b,
                "ne": lambda: a != b,
                "slt": lambda: a < b,
                "sle": lambda: a <= b,
                "sgt": lambda: a > b,
                "sge": lambda: a >= b,
                "ult": lambda: z3.ULT(a, b),
                "ule": lambda: z3.ULE(a, b),
                "ugt": lambda: z3.UGT(a, b),
                "uge": lambda: z3.UGE(a, b),
            }
        else:
            pred_map = {
                "eq": lambda: a == b,
                "ne": lambda: a != b,
                "slt": lambda: a < b,
                "sle": lambda: a <= b,
                "sgt": lambda: a > b,
                "sge": lambda: a >= b,
                "ult": lambda: a < b,
                "ule": lambda: a <= b,
                "ugt": lambda: a > b,
                "uge": lambda: a >= b,
            }

        cmp_fn = pred_map.get(pred)
        if cmp_fn:
            self._env[inst.result] = self._from_bool(cmp_fn())
        else:
            self._env[inst.result] = self._fresh_var(inst.result_type)

    def _encode_select(self, inst: Instruction) -> None:
        """Encode select i1 %cond, ty %a, ty %b."""
        if inst.result is None:
            return
        cond = (
            self._resolve_operand(inst.condition)
            if inst.condition
            else z3.BoolVal(True)
        )
        true_val = (
            self._resolve_operand(inst.true_value)
            if inst.true_value
            else z3.IntVal(0)
        )
        false_val = (
            self._resolve_operand(inst.false_value)
            if inst.false_value
            else z3.IntVal(0)
        )

        self._env[inst.result] = z3.If(self._to_bool(cond), true_val, false_val)

    def _encode_cast(self, inst: Instruction) -> None:
        """Encode sext, zext, trunc — identity in Int mode."""
        if inst.result is None or not inst.operands:
            return
        src = self._resolve_operand(inst.operands[0])

        if not self._use_bitvec:
            self._env[inst.result] = src
            return

        src_type = inst.operands[0].type
        dst_type = inst.result_type
        src_bits = src_type.bit_width if src_type else None
        dst_bits = dst_type.bit_width if dst_type else None

        if src_bits and dst_bits and z3.is_bv(src):
            if inst.opcode == "sext":
                self._env[inst.result] = z3.SignExt(dst_bits - src_bits, src)
            elif inst.opcode == "zext":
                self._env[inst.result] = z3.ZeroExt(dst_bits - src_bits, src)
            elif inst.opcode == "trunc":
                self._env[inst.result] = z3.Extract(dst_bits - 1, 0, src)
            else:
                self._env[inst.result] = src
        else:
            self._env[inst.result] = src

    def _encode_call(self, inst: Instruction) -> None:
        """Encode call instructions — handle I/O and unknown calls."""
        callee = inst.callee or ""
        io_op = _classify_io_call(callee, inst.call_args)

        if io_op is not None:
            if io_op.direction == "output":
                # Find the data argument (non-pointer type).
                data_expr = None
                for arg in inst.call_args:
                    if arg.type and arg.type.raw not in ("ptr", ""):
                        data_expr = self._resolve_operand(arg)
                        break
                if data_expr is None and len(inst.call_args) >= 2:
                    data_expr = self._resolve_operand(inst.call_args[-1])
                if data_expr is not None:
                    self._outputs.append(
                        SymbolicOutput(
                            expr=data_expr, operand_type=io_op.operand_type
                        )
                    )
                if inst.result:
                    self._env[inst.result] = self._fresh_var(inst.result_type)
                return

            elif io_op.direction == "input":
                bit_width = 32
                for arg in inst.call_args:
                    if arg.type and arg.type.raw not in ("ptr", ""):
                        bw = arg.type.bit_width
                        if bw:
                            bit_width = bw
                            break

                input_var = self._fresh_input(bit_width)

                # Associate input with the last pointer argument.
                target_ptr = None
                for arg in inst.call_args:
                    if arg.type and arg.type.raw == "ptr":
                        target_ptr = arg.name
                if target_ptr:
                    self._env[f"__input_for_{target_ptr}"] = input_var

                if inst.result:
                    self._env[inst.result] = self._fresh_var(inst.result_type)
                return

        # Unknown call — fresh symbolic variable for the result.
        if inst.result:
            self._has_unsupported = True
            self._unsupported_opcodes.add(f"call:{callee}")
            self._env[inst.result] = self._fresh_var(inst.result_type)

    def _encode_ret(self, inst: Instruction, path_cond: z3.BoolRef) -> None:
        """Encode a return instruction under a path condition."""
        if not inst.operands:
            return
        ret_val = self._resolve_operand(inst.operands[0])
        if self._return_expr is None:
            self._return_expr = ret_val
        else:
            self._return_expr = z3.If(path_cond, ret_val, self._return_expr)

    def _encode_memory(self, inst: Instruction) -> None:
        """Handle alloca, load, store — mark as unsupported."""
        self._has_unsupported = True
        self._unsupported_opcodes.add(inst.opcode)

        if inst.opcode == "alloca" and inst.result:
            self._env[inst.result] = self._fresh_var(inst.result_type)
        elif inst.opcode == "load" and inst.result:
            if inst.operands:
                ptr_name = inst.operands[0].name
                input_key = f"__input_for_{ptr_name}"
                if input_key in self._env:
                    self._env[inst.result] = self._env[input_key]
                    return
                store_key = f"__store_{ptr_name}"
                if store_key in self._env:
                    self._env[inst.result] = self._env[store_key]
                    return
            self._env[inst.result] = self._fresh_var(inst.result_type)
        elif inst.opcode == "store":
            if len(inst.operands) >= 2:
                val = self._resolve_operand(inst.operands[0])
                ptr_name = inst.operands[1].name
                self._env[f"__store_{ptr_name}"] = val

    def _encode_phi(
        self, inst: Instruction, edge_conds: dict[str, z3.BoolRef]
    ) -> None:
        """Encode a phi node using path conditions from predecessors."""
        if inst.result is None or not inst.phi_incoming:
            return

        incoming = inst.phi_incoming  # list of (value_str, label_str)

        if len(incoming) == 1:
            val_str, _ = incoming[0]
            val_operand = Operand(name=val_str, type=inst.result_type)
            self._env[inst.result] = self._resolve_operand(val_operand)
            return

        # Build nested If: last incoming is default.
        val_str, _ = incoming[-1]
        val_operand = Operand(name=val_str, type=inst.result_type)
        expr = self._resolve_operand(val_operand)

        for val_str, label_str in reversed(incoming[:-1]):
            label = label_str.lstrip("%")
            cond = edge_conds.get(label, z3.BoolVal(True))
            val_operand = Operand(name=val_str, type=inst.result_type)
            val = self._resolve_operand(val_operand)
            expr = z3.If(cond, val, expr)

        self._env[inst.result] = expr

    # -- Control flow -------------------------------------------------------

    def _build_cfg(
        self, fn: Function
    ) -> tuple[dict[str, int], list[list[str]], dict[str, list[str]]]:
        """Build CFG: label->index, successors per block, predecessors."""
        label_to_idx: dict[str, int] = {}
        for i, block in enumerate(fn.blocks):
            label_to_idx[block.label] = i

        successors: list[list[str]] = [[] for _ in range(len(fn.blocks))]
        predecessors: dict[str, list[str]] = defaultdict(list)

        for i, block in enumerate(fn.blocks):
            if not block.instructions:
                continue
            term = block.instructions[-1]
            targets: list[str] = []
            if term.opcode == "br":
                if term.dest_label:
                    targets.append(term.dest_label.lstrip("%"))
                if term.true_label:
                    targets.append(term.true_label.lstrip("%"))
                if term.false_label:
                    targets.append(term.false_label.lstrip("%"))
            for target in targets:
                if target in label_to_idx:
                    successors[i].append(target)
                    predecessors[target].append(block.label)

        return label_to_idx, successors, dict(predecessors)

    def _detect_back_edges(
        self,
        fn: Function,
        label_to_idx: dict[str, int],
        successors: list[list[str]],
    ) -> set[tuple[str, str]]:
        """Detect back-edges via DFS with WHITE/GRAY/BLACK coloring."""
        WHITE, GRAY, BLACK = 0, 1, 2
        n = len(fn.blocks)
        color = [WHITE] * n
        back_edges: set[tuple[str, str]] = set()

        def dfs(idx: int) -> None:
            color[idx] = GRAY
            block_label = fn.blocks[idx].label
            for succ_label in successors[idx]:
                succ_idx = label_to_idx.get(succ_label)
                if succ_idx is None:
                    continue
                if color[succ_idx] == GRAY:
                    back_edges.add((block_label, succ_label))
                elif color[succ_idx] == WHITE:
                    dfs(succ_idx)
            color[idx] = BLACK

        if n > 0:
            dfs(0)
            for i in range(n):
                if color[i] == WHITE:
                    dfs(i)

        return back_edges

    def _topological_order(
        self,
        fn: Function,
        label_to_idx: dict[str, int],
        successors: list[list[str]],
        back_edges: set[tuple[str, str]],
    ) -> list[str]:
        """Compute topological order of blocks, ignoring back-edges."""
        n = len(fn.blocks)
        adj: dict[str, list[str]] = defaultdict(list)
        in_degree: dict[str, int] = {
            fn.blocks[i].label: 0 for i in range(n)
        }

        for i, block in enumerate(fn.blocks):
            for succ_label in successors[i]:
                if (block.label, succ_label) not in back_edges:
                    adj[block.label].append(succ_label)
                    in_degree[succ_label] = in_degree.get(succ_label, 0) + 1

        queue = deque()
        for label in in_degree:
            if in_degree[label] == 0:
                queue.append(label)

        order: list[str] = []
        while queue:
            label = queue.popleft()
            order.append(label)
            for succ in adj.get(label, []):
                in_degree[succ] -= 1
                if in_degree[succ] == 0:
                    queue.append(succ)

        visited = set(order)
        for i in range(n):
            if fn.blocks[i].label not in visited:
                order.append(fn.blocks[i].label)

        return order

    def _get_edge_condition(
        self, from_block: BasicBlock, to_label: str
    ) -> z3.BoolRef:
        """Get the branch condition for the edge from_block -> to_label."""
        if not from_block.instructions:
            return z3.BoolVal(True)

        term = from_block.instructions[-1]
        if term.opcode != "br":
            return z3.BoolVal(True)

        if term.dest_label:
            return z3.BoolVal(True)

        if term.condition and term.true_label and term.false_label:
            cond_expr = self._resolve_operand(term.condition)
            cond_bool = self._to_bool(cond_expr)
            true_target = term.true_label.lstrip("%")
            false_target = term.false_label.lstrip("%")
            if to_label == true_target:
                return cond_bool
            elif to_label == false_target:
                return z3.Not(cond_bool)

        return z3.BoolVal(True)

    # -- Main encoding entry point ------------------------------------------

    def encode_function(self, fn: Function) -> EncodingResult:
        """Encode a function into Z3 formulas."""
        self._reset()

        for param in fn.params:
            var = self._make_z3_var(param.name, param.type)
            self._env[param.name] = var
            self._param_vars.append(var)

        if not fn.blocks:
            return self._build_result(fn.name)

        label_to_idx, successors, predecessors = self._build_cfg(fn)
        back_edges = self._detect_back_edges(fn, label_to_idx, successors)
        topo_order = self._topological_order(
            fn, label_to_idx, successors, back_edges
        )

        loop_headers = {target for _, target in back_edges}
        if loop_headers:
            self._loop_bound_hit = True

        block_map: dict[str, BasicBlock] = {b.label: b for b in fn.blocks}

        # Process blocks in topological order.
        for label in topo_order:
            block = block_map.get(label)
            if block is None:
                continue

            # Compute path condition for this block.
            if label == fn.blocks[0].label:
                path_cond = z3.BoolVal(True)
            else:
                preds = predecessors.get(label, [])
                if not preds:
                    path_cond = z3.BoolVal(False)
                else:
                    pred_conds: list[z3.BoolRef] = []
                    for pred_label in preds:
                        if (pred_label, label) in back_edges:
                            continue
                        pred_block = block_map.get(pred_label)
                        if pred_block is None:
                            continue
                        pred_path = self._block_path_cond.get(
                            pred_label, z3.BoolVal(True)
                        )
                        edge_cond = self._get_edge_condition(
                            pred_block, label
                        )
                        pred_conds.append(z3.And(pred_path, edge_cond))

                    if not pred_conds:
                        path_cond = z3.BoolVal(True)
                    elif len(pred_conds) == 1:
                        path_cond = pred_conds[0]
                    else:
                        path_cond = z3.Or(*pred_conds)

            self._block_path_cond[label] = path_cond

            # Edge conditions for phi nodes.
            edge_conds: dict[str, z3.BoolRef] = {}
            preds = predecessors.get(label, [])
            for pred_label in preds:
                if (pred_label, label) in back_edges:
                    continue
                pred_block = block_map.get(pred_label)
                if pred_block is None:
                    continue
                pred_path = self._block_path_cond.get(
                    pred_label, z3.BoolVal(True)
                )
                edge_cond = self._get_edge_condition(pred_block, label)
                edge_conds[pred_label] = z3.And(pred_path, edge_cond)

            for inst_obj in block.instructions:
                self._encode_instruction(inst_obj, path_cond, edge_conds)

        # Loop unrolling.
        if loop_headers and self._loop_bound > 1:
            self._unroll_loops(
                fn,
                block_map,
                label_to_idx,
                successors,
                predecessors,
                back_edges,
                loop_headers,
            )

        return self._build_result(fn.name)

    def _encode_instruction(
        self,
        inst: Instruction,
        path_cond: z3.BoolRef,
        edge_conds: dict[str, z3.BoolRef],
    ) -> None:
        """Dispatch an instruction to the appropriate encoder."""
        opcode = inst.opcode

        if opcode in ("add", "sub", "mul", "sdiv", "udiv", "srem", "urem"):
            self._encode_arithmetic(inst)
        elif opcode in ("and", "or", "xor", "shl", "lshr", "ashr"):
            self._encode_bitwise(inst)
        elif opcode == "icmp":
            self._encode_icmp(inst)
        elif opcode == "select":
            self._encode_select(inst)
        elif opcode in (
            "sext", "zext", "trunc", "bitcast",
            "sitofp", "fptosi", "uitofp", "fptoui",
            "fpext", "fptrunc", "inttoptr", "ptrtoint",
            "addrspacecast",
        ):
            self._encode_cast(inst)
        elif opcode == "phi":
            self._encode_phi(inst, edge_conds)
        elif opcode == "call":
            self._encode_call(inst)
        elif opcode == "ret":
            self._encode_ret(inst, path_cond)
        elif opcode in ("alloca", "load", "store"):
            self._encode_memory(inst)
        elif opcode in ("br", "switch", "unreachable"):
            pass  # Control flow handled by CFG algorithm.
        elif opcode == "getelementptr":
            if inst.result:
                self._has_unsupported = True
                self._unsupported_opcodes.add(opcode)
                self._env[inst.result] = self._fresh_var(inst.result_type)
        else:
            if inst.result:
                self._has_unsupported = True
                self._unsupported_opcodes.add(opcode)
                self._env[inst.result] = self._fresh_var(inst.result_type)

    # -- Loop unrolling -----------------------------------------------------

    def _unroll_loops(
        self,
        fn: Function,
        block_map: dict[str, BasicBlock],
        label_to_idx: dict[str, int],
        successors: list[list[str]],
        predecessors: dict[str, list[str]],
        back_edges: set[tuple[str, str]],
        loop_headers: set[str],
    ) -> None:
        """Perform encoder-level loop unrolling for K-1 additional iters."""
        for header in loop_headers:
            body_blocks = self._find_loop_body(
                header, block_map, label_to_idx, successors, back_edges
            )

            for k in range(1, self._loop_bound):
                # Update phi nodes at header: use back-edge values.
                header_block = block_map.get(header)
                if header_block is None:
                    continue

                for inst_obj in header_block.instructions:
                    if inst_obj.opcode == "phi" and inst_obj.result:
                        self._encode_phi_unrolled(
                            inst_obj, back_edges, header
                        )

                # Re-encode non-phi instructions in all body blocks.
                for blabel in body_blocks:
                    block = block_map.get(blabel)
                    if block is None:
                        continue
                    path_cond = self._block_path_cond.get(
                        blabel, z3.BoolVal(True)
                    )
                    for inst_obj in block.instructions:
                        if inst_obj.opcode == "phi":
                            continue
                        self._encode_instruction(
                            inst_obj, path_cond, {}
                        )

    def _encode_phi_unrolled(
        self,
        inst: Instruction,
        back_edges: set[tuple[str, str]],
        header_label: str,
    ) -> None:
        """Encode phi at loop header using back-edge values."""
        if inst.result is None or not inst.phi_incoming:
            return

        for val_str, label_str in inst.phi_incoming:
            label = label_str.lstrip("%")
            if (label, header_label) in back_edges:
                val_operand = Operand(name=val_str, type=inst.result_type)
                self._env[inst.result] = self._resolve_operand(val_operand)
                return

    def _find_loop_body(
        self,
        header: str,
        block_map: dict[str, BasicBlock],
        label_to_idx: dict[str, int],
        successors: list[list[str]],
        back_edges: set[tuple[str, str]],
    ) -> list[str]:
        """Find all blocks in the loop body for a given header."""
        back_sources = {src for src, tgt in back_edges if tgt == header}
        body = set(back_sources)
        body.add(header)

        reverse_adj: dict[str, list[str]] = defaultdict(list)
        for blabel, block in block_map.items():
            idx = label_to_idx.get(blabel)
            if idx is not None:
                for succ_label in successors[idx]:
                    if (blabel, succ_label) not in back_edges:
                        reverse_adj[succ_label].append(blabel)

        worklist = list(back_sources)
        while worklist:
            node = worklist.pop()
            for pred in reverse_adj.get(node, []):
                if pred not in body:
                    body.add(pred)
                    worklist.append(pred)

        # Return in original block order.
        return [b.label for b in block_map.values() if b.label in body]

    # -- Result builder -----------------------------------------------------

    def _build_result(self, fn_name: str) -> EncodingResult:
        """Build the final encoding result."""
        return EncodingResult(
            function_name=fn_name,
            inputs=list(self._inputs),
            outputs=list(self._outputs),
            return_expr=self._return_expr,
            param_vars=list(self._param_vars),
            has_unsupported=self._has_unsupported,
            unsupported_opcodes=set(self._unsupported_opcodes),
            loop_unroll_bound=self._loop_bound,
            loop_bound_hit=self._loop_bound_hit,
        )


# ---------------------------------------------------------------------------
# Equivalence checking
# ---------------------------------------------------------------------------

def check_equivalence(
    result_a: EncodingResult,
    result_b: EncodingResult,
    timeout_ms: int = 30000,
) -> EquivalenceResult:
    """Check if two encoding results are semantically equivalent."""
    bounded = result_a.loop_bound_hit or result_b.loop_bound_hit
    loop_bound = max(result_a.loop_unroll_bound, result_b.loop_unroll_bound)

    has_outputs = bool(result_a.outputs) or bool(result_b.outputs)
    has_returns = (
        result_a.return_expr is not None or result_b.return_expr is not None
    )

    if not has_outputs and not has_returns:
        return EquivalenceResult(
            verdict="EQUIVALENT",
            counterexample=None,
            details="Both functions have no observable outputs or returns.",
            bounded=bounded,
            loop_bound=loop_bound,
        )

    # Build substitution maps.
    subst_a: list[tuple[z3.ExprRef, z3.ExprRef]] = []
    subst_b: list[tuple[z3.ExprRef, z3.ExprRef]] = []

    # Unify function parameters by position.
    n_params = min(len(result_a.param_vars), len(result_b.param_vars))
    for i in range(n_params):
        pa = result_a.param_vars[i]
        pb = result_b.param_vars[i]
        if str(pa) != str(pb):
            shared = z3.Int(f"param_{i}")
            subst_a.append((pa, shared))
            subst_b.append((pb, shared))

    # Unify I/O inputs by position.
    n_inputs = min(len(result_a.inputs), len(result_b.inputs))
    for i in range(n_inputs):
        ia = result_a.inputs[i].z3_var
        ib = result_b.inputs[i].z3_var
        if str(ia) != str(ib):
            shared = z3.Int(f"shared_input_{i}")
            subst_a.append((ia, shared))
            subst_b.append((ib, shared))

    if has_outputs:
        if len(result_a.outputs) != len(result_b.outputs):
            return EquivalenceResult(
                verdict="COUNTEREXAMPLE",
                counterexample=None,
                details=(
                    f"Different number of outputs: "
                    f"{len(result_a.outputs)} vs {len(result_b.outputs)}"
                ),
                bounded=bounded,
                loop_bound=loop_bound,
            )
        exprs_a = [o.expr for o in result_a.outputs]
        exprs_b = [o.expr for o in result_b.outputs]
    else:
        if result_a.return_expr is None and result_b.return_expr is None:
            return EquivalenceResult(
                verdict="EQUIVALENT",
                counterexample=None,
                details="Both functions return void.",
                bounded=bounded,
                loop_bound=loop_bound,
            )
        if result_a.return_expr is None or result_b.return_expr is None:
            return EquivalenceResult(
                verdict="COUNTEREXAMPLE",
                counterexample=None,
                details="One function returns a value, the other returns void.",
                bounded=bounded,
                loop_bound=loop_bound,
            )
        exprs_a = [result_a.return_expr]
        exprs_b = [result_b.return_expr]

    # Apply substitutions.
    unified_a = [
        z3.substitute(e, *subst_a) if subst_a else e for e in exprs_a
    ]
    unified_b = [
        z3.substitute(e, *subst_b) if subst_b else e for e in exprs_b
    ]

    # Build query: can any output pair differ?
    diffs = [ea != eb for ea, eb in zip(unified_a, unified_b)]
    if not diffs:
        return EquivalenceResult(
            verdict="EQUIVALENT",
            counterexample=None,
            details="No outputs to compare.",
            bounded=bounded,
            loop_bound=loop_bound,
        )

    query = z3.Or(*diffs) if len(diffs) > 1 else diffs[0]

    solver = z3.Solver()
    solver.set("timeout", timeout_ms)
    solver.add(query)

    result = solver.check()

    if result == z3.unsat:
        return EquivalenceResult(
            verdict="EQUIVALENT",
            counterexample=None,
            details="Z3 proved outputs are identical for all inputs.",
            bounded=bounded,
            loop_bound=loop_bound,
        )
    elif result == z3.sat:
        model = solver.model()
        ce: dict[str, int] = {}
        for decl in model.decls():
            val = model[decl]
            try:
                ce[decl.name()] = val.as_long()
            except (AttributeError, z3.Z3Exception):
                pass
        return EquivalenceResult(
            verdict="COUNTEREXAMPLE",
            counterexample=ce,
            details=f"Found inputs where outputs differ: {ce}",
            bounded=bounded,
            loop_bound=loop_bound,
        )
    else:
        return EquivalenceResult(
            verdict="UNKNOWN",
            counterexample=None,
            details=(
                "Z3 could not determine equivalence "
                "(timeout or resource limit)."
            ),
            bounded=bounded,
            loop_bound=loop_bound,
        )


# ---------------------------------------------------------------------------
# Public API convenience functions
# ---------------------------------------------------------------------------

def encode_function(
    fn: Function,
    *,
    loop_bound: int = 10,
    timeout_ms: int = 30000,
    use_bitvec: bool = False,
) -> EncodingResult:
    """Encode a parsed LLVM IR function into Z3 formulas."""
    encoder = Z3Encoder(loop_bound=loop_bound, use_bitvec=use_bitvec)
    return encoder.encode_function(fn)


def check_equivalence_functions(
    fn_a: Function,
    fn_b: Function,
    *,
    loop_bound: int = 10,
    timeout_ms: int = 30000,
    use_bitvec: bool = False,
) -> EquivalenceResult:
    """Encode two functions and check their equivalence."""
    result_a = encode_function(
        fn_a, loop_bound=loop_bound,
        timeout_ms=timeout_ms, use_bitvec=use_bitvec,
    )
    result_b = encode_function(
        fn_b, loop_bound=loop_bound,
        timeout_ms=timeout_ms, use_bitvec=use_bitvec,
    )
    return check_equivalence(result_a, result_b, timeout_ms=timeout_ms)


def check_equivalence_cpp(
    file_a: str | Path,
    file_b: str | Path,
    *,
    function_name: str | None = None,
    loop_bound: int = 10,
    timeout_ms: int = 30000,
    use_bitvec: bool = False,
    clang_path: str | Path | None = None,
    opt_path: str | Path | None = None,
) -> EquivalenceResult:
    """End-to-end: compile two C++ files and check semantic equivalence."""
    from semantic_equiv.normalize import normalize_cpp

    file_a = Path(file_a)
    file_b = Path(file_b)

    with tempfile.TemporaryDirectory(prefix="semantic_z3_") as tmpdir:
        norm_a = normalize_cpp(
            file_a, output_dir=Path(tmpdir) / "a",
            clang_path=clang_path, opt_path=opt_path,
        )
        norm_b = normalize_cpp(
            file_b, output_dir=Path(tmpdir) / "b",
            clang_path=clang_path, opt_path=opt_path,
        )

        mod_a = parse_llvm_ir(norm_a)
        mod_b = parse_llvm_ir(norm_b)

    if function_name:
        fn_name = (
            function_name
            if function_name.startswith("@")
            else f"@{function_name}"
        )
        fn_a = mod_a.get_function(fn_name)
        fn_b = mod_b.get_function(fn_name)
        if fn_a is None or fn_b is None:
            return EquivalenceResult(
                verdict="UNKNOWN",
                counterexample=None,
                details=f"Function {fn_name} not found in one or both modules.",
                bounded=False,
                loop_bound=loop_bound,
            )
        return check_equivalence_functions(
            fn_a, fn_b,
            loop_bound=loop_bound,
            timeout_ms=timeout_ms,
            use_bitvec=use_bitvec,
        )

    fn_a = mod_a.get_function("@main")
    fn_b = mod_b.get_function("@main")
    if fn_a and fn_b:
        return check_equivalence_functions(
            fn_a, fn_b,
            loop_bound=loop_bound,
            timeout_ms=timeout_ms,
            use_bitvec=use_bitvec,
        )

    names_a = {fn.name for fn in mod_a.functions}
    names_b = {fn.name for fn in mod_b.functions}
    common = sorted(names_a & names_b)
    if common:
        fn_a = mod_a.get_function(common[0])
        fn_b = mod_b.get_function(common[0])
        if fn_a and fn_b:
            return check_equivalence_functions(
                fn_a, fn_b,
                loop_bound=loop_bound,
                timeout_ms=timeout_ms,
                use_bitvec=use_bitvec,
            )

    return EquivalenceResult(
        verdict="UNKNOWN",
        counterexample=None,
        details="No matching functions found to compare.",
        bounded=False,
        loop_bound=loop_bound,
    )
