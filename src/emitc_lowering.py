#!/usr/bin/env python3
"""
emitc_lowering.py: Lower COBOL MLIR dialect to EmitC dialect

TBD: This module will implement lowering from the COBOL dialect to EmitC,
enabling generation of C code from COBOL programs.
"""

from cobol_dialect import (
    COBOL,
    CobolDecimalType,
    CobolStringType,
    AcceptOp,
    AddOp,
    ConstantOp,
    DeclareOp,
    DisplayOp,
    FunctionOp,
    IsOp,
    MoveOp,
    NotOp,
    SetOp,
    StopRunOp
)
from dataclasses import dataclass
from xdsl.builder import InsertPoint
from xdsl.context import Context
from xdsl.dialects.builtin import (
    AnyTensorType,
    DenseIntOrFPElementsAttr,
    FunctionType,
    I8,
    IntAttr,
    IntegerAttr,
    IntegerType,
    MemRefType,
    ModuleOp,
    StringAttr,
    TensorType,
    UnitAttr
)
from xdsl.dialects import emitc
from xdsl.dialects.emitc import (
    EmitC,
    EmitC_AddOp,
    EmitC_ApplyOp,
    EmitC_AssignOp,
    EmitC_CallOpaqueOp,
    EmitC_ConstantOp,
    EmitC_VariableOp,
    EmitC_LValueType,
    EmitCIntegerType,
    EmitC_OpaqueType
)
from xdsl.dialects.func import FuncOp, ReturnOp

from xdsl.pattern_rewriter import (
    GreedyRewritePatternApplier,
    PatternRewriter,
    PatternRewriteWalker,
    RewritePattern,
    TypeConversionPattern,
    attr_type_rewrite_pattern,
    op_type_rewrite_pattern
)
from xdsl.passes import ModulePass
import math


class CobolDecimalTypeConversion(TypeConversionPattern):
    @attr_type_rewrite_pattern
    def convert_type(self, type: CobolDecimalType) -> EmitCIntegerType:
        num_digits = type.digits.value.data
        num_bits = math.ceil(num_digits * 3.32)

        if num_bits < 2**8:
            return EmitCIntegerType(8)
        elif num_bits < 2**16:
            return EmitCIntegerType(16)
        elif num_bits < 2**32:
            return EmitCIntegerType(32)
        elif num_bits < 2**64:
            return EmitCIntegerType(64)
        else:
            return "error" # ...


class CobolStringTypeConversion(TypeConversionPattern):
    @attr_type_rewrite_pattern
    def convert_type(self, type: CobolStringType) -> EmitC_OpaqueType:
        return emitc.EmitC_PointerType(EmitC_OpaqueType(StringAttr(f"char[{type.length}]")))


@dataclass
class ConvertAcceptOp(RewritePattern):
    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: AcceptOp, rewriter: PatternRewriter):
        print("Rewriting accept op")


# TO DO
@dataclass
class ConvertConstantOp(RewritePattern):
    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: ConstantOp, rewriter: PatternRewriter):
        print("Rewriting constant op")


# TO DO
@dataclass
class ConvertDeclareOp(RewritePattern): # postaje variable
    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: DeclareOp, rewriter: PatternRewriter):
        sym_name = op.attributes["sym_name"]

        if isinstance(op.result.type, IntegerType):
            emitc_type = op.result.type
        elif isinstance(op.result.type, emitc.EmitC_PointerType):
            emitc_type = op.result.type

        var  = EmitC_VariableOp(
            emitc.EmitC_OpaqueAttr(sym_name),
            EmitC_LValueType(emitc_type))

        print(var)
        rewriter.replace_op(op, var)


@dataclass
class ConvertDisplayOp(RewritePattern):
    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: DisplayOp, rewriter: PatternRewriter):
        print("Rewriting display op")


@dataclass
class ConvertFuncOp(RewritePattern):
    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: FunctionOp, rewriter: PatternRewriter, /):
        new_func = FuncOp(
            op.attributes["sym_name"].data,
            FunctionType.from_lists([], []),
            region=op.body.clone()
        )
        rewriter.replace_op(op, new_func)
        return


@dataclass
class ConvertIsOp(RewritePattern):
    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: IsOp, rewriter: PatternRewriter):
        print("Rewriting is op")


# TO DO
@dataclass
class ConvertMoveOp(RewritePattern):
    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: MoveOp, rewriter: PatternRewriter):
        print("Rewriting move op")


@dataclass
class ConvertNotOp(RewritePattern):
    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: NotOp, rewriter: PatternRewriter):
        print("Rewriting not op")


@dataclass
class ConvertSetOp(RewritePattern):
    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: SetOp, rewriter: PatternRewriter):
        print("Rewriting set op")


@dataclass
class ConvertStopOp(RewritePattern):
    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: StopRunOp, rewriter: PatternRewriter):
        rewriter.replace_op(op, ReturnOp())
        return


class ConvertCobolToEmitcPass(ModulePass):
    """
    Converts cobol dialect to emitc dialect.
    """

    name = "convert_cobol_to_emitc"

    def apply(self, ctx: Context, op: ModuleOp) -> None:
        PatternRewriteWalker(
            GreedyRewritePatternApplier(
                [
                    CobolDecimalTypeConversion(),
                    CobolStringTypeConversion(),
                    ConvertAcceptOp(),
                    ConvertConstantOp(),
                    ConvertDeclareOp(),
                    ConvertDisplayOp(),
                    ConvertFuncOp(),
                    ConvertStopOp(),
                    ConvertIsOp(),
                    ConvertMoveOp(),
                    ConvertNotOp(),
                    ConvertStopOp(),
                    ConvertSetOp()
                ]
            ),
            apply_recursively=True
        ).rewrite_module(op)


def lower_to_emitc(module):
    """Lower a COBOL MLIR module to EmitC dialect.

    Args:
        module: The COBOL MLIR module to lower

    Returns:
        The lowered EmitC module
    """

    ConvertCobolToEmitcPass().apply(Context(), module)

    return None
