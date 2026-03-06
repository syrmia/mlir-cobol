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
    CobolRecordType,
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
    StopRunOp,
    StructOp,
    SubOp,
)
from dataclasses import dataclass
from xdsl.context import Context
from xdsl.dialects.builtin import (
    AnyFloat,
    Float32Type,
    Float64Type,
    FunctionType,
    IntegerAttr,
    IntegerType,
    ModuleOp,
    StringAttr,
    SymbolRefAttr,
    UnitAttr,
)
from xdsl.dialects import emitc
from xdsl.dialects.emitc import (
    EmitC,
    EmitC_AddOp,
    EmitC_AssignOp,
    EmitC_ClassOp,
    EmitC_ConstantOp,
    EmitC_CmpOp,
    EmitC_IfOp,
    EmitC_IncludeOp,
    EmitC_LoadOp,
    EmitC_LogicalAndOp,
    EmitC_LogicalOrOp,
    EmitC_VariableOp,
    EmitC_VerbatimOp,
    EmitC_LValueType,
    EmitCIntegerType,
    EmitC_OpaqueType,
    EmitC_OpaqueAttr,
    EmitC_PointerType,
    EmitC_SubOp,
)
from xdsl.dialects.func import FuncOp, ReturnOp
from xdsl.dialects.scf import IfOp, YieldOp
from xdsl.passes import ModulePass
from xdsl.pattern_rewriter import (
    GreedyRewritePatternApplier,
    PatternRewriter,
    PatternRewriteWalker,
    RewritePattern,
    TypeConversionPattern,
    attr_type_rewrite_pattern,
    op_type_rewrite_pattern,
)
from xdsl.rewriter import InsertPoint


class CobolBoolTypeConversion(TypeConversionPattern):
    @attr_type_rewrite_pattern
    def convert_type(self, typ: CobolBoolType) -> EmitCIntegerType:
        return EmitCIntegerType(1)


class CobolDecimalTypeConversion(TypeConversionPattern):
    @attr_type_rewrite_pattern
    def convert_type(self, type: CobolDecimalType) -> EmitCIntegerType:
        length = type.digits.value.data
        scale = type.scale.value.data

        if scale:
            digits = length + scale
            if digits <= 7:
                return Float32Type()
            return Float64Type()
        else:
            for width in (8, 16, 32, 64):
                if 10**length - 1 < 2**width:
                    return EmitCIntegerType(width)

        return "error"  # ...


class CobolStringTypeConversion(TypeConversionPattern):
    @attr_type_rewrite_pattern
    def convert_type(self, type: CobolStringType) -> EmitC_PointerType:
        return EmitC_LValueType(EmitC_OpaqueType(StringAttr("std::string")))


class CobolRecordTypeConversion(TypeConversionPattern):
    @attr_type_rewrite_pattern
    def convert_type(self, type: CobolRecordType) -> EmitC_PointerType:
        return EmitC_LValueType(EmitC_OpaqueType(type.record_name))


@dataclass
class ConvertAcceptOp(RewritePattern):
    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: AcceptOp, rewriter: PatternRewriter):
        args = op.args
        string_arg = "std::cin >> {};"
        verbatim_op = EmitC_VerbatimOp(value=StringAttr(string_arg), operands=args)
        rewriter.replace_op(op, verbatim_op)


@dataclass
class ConvertAddOp(RewritePattern):
    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: AddOp, rewriter: PatternRewriter):
        load_frst = EmitC_LoadOp(op.operands[0])
        load_scnd = EmitC_LoadOp(op.operands[1])

        rewriter.insert_op(load_frst, InsertPoint.before(op))
        rewriter.insert_op(load_scnd, InsertPoint.before(op))

        add_op = EmitC_AddOp(
            load_frst.result,
            load_scnd.result,
            op.result.type,
        )
        rewriter.replace_op(op, add_op)

        if op.properties["kind"].data == "compute":
            return

        assign_op = EmitC_AssignOp(
            var=op.operands[1],
            value=add_op.result,
        )
        rewriter.insert_op(assign_op, InsertPoint.after(add_op))


@dataclass
class ConvertAndIOp(RewritePattern):
    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: AndIOp, rewriter: PatternRewriter):
        and_op = EmitC_LogicalAndOp(op.operands[0], op.operands[1], IntegerType(1))
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
            op.properties["predicate"].value.data, load_frst, load_scnd, IntegerType(1)
        )
        rewriter.replace_op(op, cmp_op)


@dataclass
class ConvertConstantOp(RewritePattern):
    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: ConstantOp, rewriter: PatternRewriter):
        val = op.attributes["value"]

        if isinstance(val, IntegerAttr):
            const_op = EmitC_ConstantOp(value=val)
        else:
            fixed_string = '"' + val.data.strip('"').strip("'") + '"'
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

        #print("sym_name ", sym_value)
        #print("op res type ", op_res_type)

        if isinstance(op_res_type, IntegerType):
            #print("Integer je")
            var_op = EmitC_VariableOp(
                EmitC_OpaqueAttr(StringAttr(str(sym_value.value.data))),
                EmitC_LValueType(op_res_type),
            )
            #print(var_op)
            rewriter.replace_op(op, var_op)

        elif isinstance(op_res_type, AnyFloat):
            #print("Float je")
            var_op = EmitC_VariableOp(
                EmitC_OpaqueAttr(StringAttr(str(sym_value.value.data))),
                EmitC_LValueType(op_res_type),
            )
            rewriter.replace_op(op, var_op)

        elif isinstance(op_res_type, EmitC_LValueType):
            # either std::string or custom user type (struct/class)
            opaque_type = op_res_type.value_type.value.data

            if opaque_type == "std::string":
                #print("String je")
                fixed_string = sym_value.data.strip('"').strip("'")
                var_op = EmitC_VariableOp(
                    EmitC_OpaqueAttr(
                        StringAttr('"' + fixed_string + '"')),
                        op_res_type
                )
                #print(var_op)
                rewriter.replace_op(op, var_op)
            else:
                # custom type (struct)
                #print("Struct je")
                var_op = EmitC_VariableOp(
                    EmitC_OpaqueAttr(StringAttr(opaque_type)),
                    op_res_type
                )
                #print(var_op)
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
            value=StringAttr(string_arg), operands=list(args)
        )
        rewriter.replace_op(op, verbatim_op)


@dataclass
class ConvertFuncOp(RewritePattern):
    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: FunctionOp, rewriter: PatternRewriter, /):
        new_func = FuncOp(
            op.attributes["sym_name"].data.replace("-", "_"),
            FunctionType.from_lists([], []),
            region=op.body.clone(),
        )
        rewriter.replace_op(op, new_func)
        return


@dataclass
class ConvertIfOp(RewritePattern):
    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: IfOp, rewriter: PatternRewriter):
        new_then = op.true_region.clone()
        new_else = op.false_region.clone()

        new_if = EmitC_IfOp(op.cond, new_then, new_else)
        rewriter.replace_op(op, new_if)


@dataclass
class ConvertYieldOp(RewritePattern):
    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: YieldOp, rewriter: PatternRewriter):
        rewriter.erase_op(op)


@dataclass
class ConvertIsOp(RewritePattern):
    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: IsOp, rewriter: PatternRewriter):
        print("Rewriting is op")
        # to do
        """print(op.properties)
        kind_type = op.properties["kind"].data
        is_pos = op.properties["is_positive"].data
        match kind_type:
            case "numeric":
                print("numeric je")
                print("op type ", op.operands[0].type.value_type)
                val_t = op.operands[0].type.value_type
                call_op = CallOp(
                    "std::is_arithmetic",
                    [op.operands[0]],
                    [IntegerType(1)]
                )
                rewriter.replace_op(op, call_op)"""


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
        or_op = EmitC_LogicalOrOp(op.operands[0], op.operands[1], IntegerType(1))
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


@dataclass
class ConvertStructOp(RewritePattern):
    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: StructOp, rewriter: PatternRewriter):
        struct_name = StringAttr(op.attributes["struct_name"].data.replace("-", "_"))

        struct_name_ref = SymbolRefAttr(struct_name)
        new_struct_body = op.body.clone()
        res_type = EmitC_LValueType(EmitC_OpaqueType(struct_name))

        # class definition
        class_op = EmitC_ClassOp(
            struct_name_ref,
            new_struct_body,
        )
        rewriter.insert_op(class_op, InsertPoint.before(rewriter.current_operation))

        # variable instance of the struct type
        var_op = EmitC_VariableOp(
            EmitC_OpaqueAttr(struct_name),
            res_type,
        )
        rewriter.replace_op(op, var_op)


@dataclass
class ConvertSubOp(RewritePattern):
    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: SubOp, rewriter: PatternRewriter):
        load_frst = EmitC_LoadOp(op.operands[0])
        load_scnd = EmitC_LoadOp(op.operands[1])

        rewriter.insert_op(load_frst, InsertPoint.before(op))
        rewriter.insert_op(load_scnd, InsertPoint.before(op))

        sub_op = EmitC_SubOp(
            load_scnd.result,
            load_frst.result,
            op.result.type,
        )
        rewriter.replace_op(op, sub_op)

        assign_op = EmitC_AssignOp(
            var=op.operands[1],
            value=sub_op.result,
        )
        rewriter.insert_op(assign_op, InsertPoint.after(sub_op))


class ConvertCobolToEmitcPass(ModulePass):
    """
    Converts cobol dialect to emitc dialect.
    """

    name = "convert_cobol_to_emitc"

    def add_includes(self, module: ModuleOp) -> None:
        includes_to_add = []

        for op in module.walk():
            if (
                isinstance(op, DisplayOp) or isinstance(op, AcceptOp)
            ) and "iostream" not in includes_to_add:
                includes_to_add.append("iostream")
            elif isinstance(op, DeclareOp):
                if (
                    isinstance(op.attributes["value"], IntegerAttr)
                    and "cstdint" not in includes_to_add
                ):
                    includes_to_add.append("cstdint")
                elif (
                    isinstance(op.attributes["value"], StringAttr)
                    and "string" not in includes_to_add
                ):
                    includes_to_add.append("string")

        for inc in includes_to_add:
            include_op = EmitC_IncludeOp(StringAttr(inc), UnitAttr())
            module.body.block.insert_op_before(include_op, module.body.block.first_op)

    def apply(self, ctx: Context, op: ModuleOp) -> None:
        self.add_includes(op)

        PatternRewriteWalker(
            GreedyRewritePatternApplier(
                [
                    CobolBoolTypeConversion(),
                    CobolDecimalTypeConversion(),
                    CobolStringTypeConversion(),
                    CobolRecordTypeConversion(),
                    ConvertAcceptOp(),
                    ConvertAddOp(),
                    ConvertAndIOp(),
                    ConvertCmpIOp(),
                    ConvertConstantOp(),
                    ConvertDeclareOp(),
                    ConvertDisplayOp(),
                    ConvertFuncOp(),
                    ConvertStopOp(),
                    ConvertIfOp(),
                    ConvertYieldOp(),
                    ConvertIsOp(),
                    ConvertMoveOp(),
                    ConvertNotOp(),
                    ConvertOrIOp(),
                    ConvertStopOp(),
                    ConvertSetOp(),
                    ConvertStructOp(),
                    ConvertSubOp(),
                    # RemoveUnusedOperations()
                ]
            ),
            apply_recursively=True,
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
