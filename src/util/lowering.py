
'''
lowering.py -> Partial lowering from Cobol dialect to builtin dialect: Emitc -> to do
'''

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
from xdsl.dialects.builtin import ( # ovde svasta ne treba?
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
    TypeConversionPattern,
    attr_type_rewrite_pattern,
    op_type_rewrite_pattern
)
from xdsl.passes import ModulePass


'''
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
'''

class CobolDecimalTypeConversion(TypeConversionPattern):
    @attr_type_rewrite_pattern
    def convert_type(self, typ: CobolDecimalType) -> emitc.EmitCIntegerType:
        print("Int conversion: ", emitc.EmitCIntegerType)
        return emitc.EmitCIntegerType


# hoce li biti string -> pointer?
class CobolStringTypeConversion(TypeConversionPattern):
    @attr_type_rewrite_pattern
    def convert_type(self, typ: CobolStringType) -> emitc.EmitC_PointerType:
        print("String conversion: ", emitc.EmitC_PointerType)
        return emitc.EmitC_PointerType


@dataclass
class ConvertAcceptOp(RewritePattern):
    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: AcceptOp, rewriter: PatternRewriter):
        print("Rewriting accept op")


@dataclass
class ConvertConstantOp(RewritePattern):
    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: ConstantOp, rewriter: PatternRewriter):
        print("Rewriting constant op")


@dataclass
class ConvertDeclareOp(RewritePattern):
    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: DeclareOp, rewriter: PatternRewriter):
        print("Rewriting declare op")


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
        print("Rewriting func op")
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
        print("Rewriting stop op")
        rewriter.replace_op(op, ReturnOp())
        return


class ConvertCobolToEmitcPass(ModulePass):
    """
    Converts cobol dialect to emitc dialect.
    """

    name = "convert_cobol_to_emitc"

    def apply(self, ctx: Context, op: ModuleOp) -> None:
        print("Applying pass ")
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
