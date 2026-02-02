#!/usr/bin/env python3
"""
emitc_lowering.py: Lower COBOL MLIR dialect to EmitC dialect

TBD: This module will implement lowering from the COBOL dialect to EmitC,
enabling generation of C code from COBOL programs.
"""

from cobol_dialect import (
    COBOL,
    CobolBoolType,
    CobolDecimalType,
    CobolStringType,
    AcceptOp,
    AddOp,
    AndIOp,
    ConstantOp,
    CmpIOp,
    DeclareOp,
    DisplayOp,
    FunctionOp,
    IsOp,
    MoveOp,
    NotOp,
    OrIOp,
    SetOp,
    StopRunOp
)
from dataclasses import dataclass
from xdsl.context import Context
from xdsl.dialects.builtin import (
    FunctionType,
    IntegerAttr,
    IntegerType,
    ModuleOp,
    StringAttr,
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
    EmitC_CmpOp,
    EmitC_IncludeOp,
    EmitC_LoadOp,
    EmitC_LogicalAndOp,
    EmitC_LogicalOrOp,
    EmitC_VariableOp,
    EmitC_VerbatimOp,
    EmitC_ArrayType,
    EmitCFloatType, Float16Type, BFloat16Type, Float32Type, Float64Type,
    EmitC_LValueType,
    EmitCIntegerType,
    EmitC_OpaqueType,
    EmitC_OpaqueAttr,
    EmitC_PointerType
)
from xdsl.dialects.func import FuncOp, ReturnOp
from xdsl.passes import ModulePass
from xdsl.pattern_rewriter import (
    GreedyRewritePatternApplier,
    PatternRewriter,
    PatternRewriteWalker,
    RewritePattern,
    TypeConversionPattern,
    attr_type_rewrite_pattern,
    op_type_rewrite_pattern
)
from xdsl.rewriter import InsertPoint
from xdsl.transforms.convert_scf_to_cf import IfLowering

class CobolBoolTypeConversion(TypeConversionPattern):
    @attr_type_rewrite_pattern
    def convert_type(self, typ: CobolBoolType) -> EmitCIntegerType:
        return EmitCIntegerType(1)


class CobolDecimalTypeConversion(TypeConversionPattern):
    @attr_type_rewrite_pattern
    def convert_type(self, type: CobolDecimalType) -> EmitCIntegerType:
        length = type.digits.value.data
        scale = type.scale.value.data

        #print("len: ", length, " scale: ", scale)

        if scale: # to do: floats
            digits = length + scale
            if digits <= 4:
                return Float16Type
            if digits <= 7:
                return Float32Type
            return Float64Type
        else:
            for width in (8, 16, 32, 64):
                if 10**length - 1 < 2**width:
                    return EmitCIntegerType(width)

        return "error" # ...


class CobolStringTypeConversion(TypeConversionPattern):
    @attr_type_rewrite_pattern
    def convert_type(self, type: CobolStringType) -> EmitC_PointerType:
        return EmitC_LValueType(EmitC_OpaqueType(StringAttr("std::string")))
        #return EmitC_ArrayType([type.length.value.data + 1], EmitCIntegerType(8))


@dataclass
class ConvertAcceptOp(RewritePattern):
    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: AcceptOp, rewriter: PatternRewriter):
        args = op.args
        string_arg = "std::cin >> {};"
        verbatim_op = EmitC_VerbatimOp(
            value=StringAttr(string_arg),
            operands=args
        )
        rewriter.replace_op(op, verbatim_op)


@dataclass
class ConvertAndIOp(RewritePattern):
    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: AndIOp, rewriter: PatternRewriter):
        and_op = EmitC_LogicalAndOp(
            op.operands[0],
            op.operands[1],
            IntegerType(1)
        )
        rewriter.replace_op(op, and_op)


@dataclass
class ConvertCmpIOp(RewritePattern):
    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: CmpIOp, rewriter: PatternRewriter):
        load_frst = EmitC_LoadOp(op.operands[0])
        load_scnd = EmitC_LoadOp(op.operands[1])

        rewriter.insert_op(load_frst, InsertPoint.before(op))
        rewriter.insert_op(load_scnd, InsertPoint.before(op))

        cmp_op = EmitC_CmpOp(
            op.properties["predicate"].value.data,
            load_frst, #op.operands[0],
            load_scnd, #op.operands[1],
            IntegerType(1)
        )
        rewriter.replace_op(op, cmp_op)


@dataclass
class ConvertConstantOp(RewritePattern):
    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: ConstantOp, rewriter: PatternRewriter):
        val = op.attributes["value"]

        if isinstance(val, IntegerAttr):
            const_op = EmitC_ConstantOp(
                value=val
            )
        else:
            fixed_string = "\"" + val.data.strip("\"").strip("\'") + "\""
            const_op = EmitC_ConstantOp(
                value=EmitC_OpaqueAttr(StringAttr(fixed_string))
            )
        rewriter.replace_op(op, const_op)


@dataclass
class ConvertDeclareOp(RewritePattern):
    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: DeclareOp, rewriter: PatternRewriter):
        sym_value = op.attributes["value"]
        op_res_type = op.result.type

        if isinstance(op_res_type, IntegerType):
            var_op = EmitC_VariableOp(
                EmitC_OpaqueAttr(StringAttr(str(sym_value.value.data))),
                EmitC_LValueType(op_res_type)
            )
            rewriter.replace_op(op, var_op)

        elif isinstance(op_res_type, EmitC_LValueType | EmitC_ArrayType):
            fixed_string = sym_value.data.strip("\"").strip("\'")
            var_op  = EmitC_VariableOp(
                EmitC_OpaqueAttr(StringAttr("\"" + fixed_string + "\"")),
                op_res_type
            )
            rewriter.replace_op(op, var_op)

        else:
            print("Type still not supported: ", op_res_type)

        return


@dataclass
class ConvertDisplayOp(RewritePattern):
    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: DisplayOp, rewriter: PatternRewriter):
        args = op.args
        placeholders = " << ".join("{}" for a in args)
        string_arg = "std::cout << " + placeholders + ";"
        verbatim_op = EmitC_VerbatimOp(
            value=StringAttr(string_arg),
            operands=list(args)
        )
        rewriter.replace_op(op, verbatim_op)


@dataclass
class ConvertFuncOp(RewritePattern):
    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: FunctionOp, rewriter: PatternRewriter, /):
        new_func = FuncOp(
            op.attributes["sym_name"].data.replace('-', '_'),
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


@dataclass
class ConvertMoveOp(RewritePattern):
    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: MoveOp, rewriter: PatternRewriter):
        new_op = EmitC_AssignOp(
            var=op.dst,
            value=op.src,
        )
        rewriter.replace_op(op, new_op)


@dataclass
class ConvertNotOp(RewritePattern):
    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: NotOp, rewriter: PatternRewriter):
        print("Rewriting not op")


@dataclass
class ConvertOrIOp(RewritePattern):
    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: OrIOp, rewriter: PatternRewriter):
        or_op = EmitC_LogicalOrOp(
            op.operands[0],
            op.operands[1],
            IntegerType(1)
        )
        rewriter.replace_op(op, or_op)


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

    def add_includes(self, module: ModuleOp) -> None:
        includes_to_add = []

        for op in module.walk():
            if (isinstance(op, DisplayOp) or isinstance(op, AcceptOp)) and "iostream" not in includes_to_add:
                includes_to_add.append("iostream")
            elif isinstance(op, DeclareOp):
                if isinstance(op.attributes["value"], IntegerAttr) and "cstdint" not in includes_to_add:
                    includes_to_add.append("cstdint")
                elif isinstance(op.attributes["value"], StringAttr) and "string" not in includes_to_add:
                    includes_to_add.append("string")

        for inc in includes_to_add:
            include_op = EmitC_IncludeOp(
                StringAttr(inc), UnitAttr()
            )
            module.body.block.insert_op_before(include_op, module.body.block.first_op)


    def apply(self, ctx: Context, op: ModuleOp) -> None:
        self.add_includes(op)

        PatternRewriteWalker(
            GreedyRewritePatternApplier(
                [
                    CobolBoolTypeConversion(),
                    CobolDecimalTypeConversion(),
                    CobolStringTypeConversion(),
                    ConvertAcceptOp(),
                    ConvertAndIOp(),
                    ConvertCmpIOp(),
                    ConvertConstantOp(),
                    ConvertDeclareOp(),
                    ConvertDisplayOp(),
                    ConvertFuncOp(),
                    ConvertStopOp(),
                    ConvertIsOp(),
                    ConvertMoveOp(),
                    ConvertNotOp(),
                    ConvertOrIOp(),
                    ConvertStopOp(),
                    ConvertSetOp(),
                    IfLowering()
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

    return module
