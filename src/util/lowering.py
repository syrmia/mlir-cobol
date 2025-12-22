
'''
lowering.py -> Partial lowering from Cobol dialect to builtin dialects: to do
'''

from cobol_dialect import (
    COBOL,
    CobolDecimalType,
    CobolStringType,
    AddOp,
    ConstantOp,
    DeclareOp,
    DisplayOp,
    FunctionOp,
    MoveOp,
    SetOp,
    StopRunOp
)
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
from xdsl.dialects.emitc import EmitC
from xdsl.dialects.func import FuncOp, ReturnOp
from xdsl.dialects.memref import GetGlobalOp, GlobalOp
from xdsl.dialects.printf import Printf, PrintFormatOp
from xdsl.ir import Block, ErasedSSAValue, OpResult, Region
from xdsl.pattern_rewriter import (
    GreedyRewritePatternApplier,
    PatternRewriter,
    PatternRewriteWalker,
    RewritePattern,
    op_type_rewrite_pattern
)
from xdsl.passes import ModulePass
from xdsl.transforms.canonicalize import CanonicalizePass
from xdsl.transforms.dead_code_elimination import DeadCodeElimination, region_dce

class LowerDisplayOp(RewritePattern):
    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: DisplayOp, rewriter: PatternRewriter):
        if not isinstance(op, DisplayOp):
            return

        arg = op.operands[0]

        if isinstance(arg, ErasedSSAValue):
            literal = arg.old_value
        else:
            string_attr = arg.owner.attributes["value"]
            literal = string_attr.data

        #print("iz display: ", literal)

        new_op = PrintFormatOp(literal)

        rewriter.replace_op(op, new_op)

        return


class LowerConstOp(RewritePattern):
    def match_and_rewrite(self, op: ConstantOp, rewriter: PatternRewriter):
        if not isinstance(op, ConstantOp):
            return

        literal = op.attributes.get("value").data
        #print(literal)

        bytes = [ord(c) for c in literal]
        i8 = IntegerType(8)

        shape = [IntAttr(len(bytes))]
        mem_ref = MemRefType(i8, shape)

        dense = DenseIntOrFPElementsAttr.from_list(mem_ref, bytes)

        name = "@" + literal.lower().replace(" ", "_") + "_string"

        new_op = GlobalOp(
            properties={"sym_name":StringAttr(name),
                    "sym_visibility": StringAttr("private"),
                    "type":mem_ref,
                    "initial_value": dense,
                    "constant": UnitAttr()
                    })

        for res in op.results:
            rewriter.replace_all_uses_with(res, ErasedSSAValue(StringAttr(literal), literal))

        rewriter.insert_op(new_op, InsertPoint.before(rewriter.current_operation))
        rewriter.erase_op(op)

        return


class LowerFuncOp(RewritePattern):
    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: FunctionOp, rewriter: PatternRewriter):

        new_func = FuncOp(
            op.attributes["sym_name"].data,
            FunctionType.from_lists([], []),
            region=op.body.clone()
        )

        rewriter.replace_op(op, new_func)
        return


class LowerDeclareOp(RewritePattern):
    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: DeclareOp, rewriter: PatternRewriter):

        var_name = op.attributes.get("sym_name").data
        value = op.attributes.get("value").data

        print(var_name)
        print(value)

        new_op = GlobalOp(
            properties={
                "sym_name":StringAttr(var_name),
                "sym_visibility": StringAttr("private"),
                "initial_value": value
            }
        )

        for res in op.results:
            rewriter.replace_all_uses_with(res, ErasedSSAValue(StringAttr(var_name), value))

        rewriter.insert_op(new_op, InsertPoint.before(rewriter.current_operation))
        rewriter.erase_op(op)

        return


class LowerStopOp(RewritePattern):
    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: StopRunOp, rewriter: PatternRewriter):
        rewriter.replace_op(op, ReturnOp())
        return


class LowerCobolDialectPass():
    ''' A pass for lowering custom cobol dialect into builtin xdsl dialects '''

    name = "lower-cobol-dialect"

    def apply(self, ctx: Context, op: ModuleOp):

        walker = PatternRewriteWalker(
            GreedyRewritePatternApplier(
                [
                    LowerFuncOp(),
                    LowerDisplayOp(),
                    LowerConstOp(),
                    LowerStopOp(),
                    LowerDeclareOp()
                ]
            )
        )
        walker.rewrite_module(op)


def lower_cobol_to_mlir(ctx, module):
    LowerCobolDialectPass().apply(ctx, module)
    DeadCodeElimination().apply(ctx, module)
    #CanonicalizePass().apply(ctx, module)
