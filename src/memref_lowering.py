
from dataclasses import dataclass
from xdsl.dialects.arith import ExtSIOp
from xdsl.dialects.emitc import EmitC_ConstantOp
from xdsl.dialects.memref import AllocOp, LoadOp, StoreOp, MemRefType
from xdsl.dialects.builtin import Float64Type, IndexType, IntegerAttr, IntegerType, MemRefType, ModuleOp, StringAttr, UnitAttr, i1, i16, i32, i64, i8
from xdsl.context import Context
from xdsl.passes import ModulePass
from xdsl.rewriter import InsertPoint
from cobol_dialect import AcceptOp, CobolBoolType, CobolDecimalType, CobolStringType, DeclareOp, DisplayOp, MoveOp
from xdsl.pattern_rewriter import (
    GreedyRewritePatternApplier,
    PatternRewriter,
    PatternRewriteWalker,
    RewritePattern,
    TypeConversionPattern,
    attr_type_rewrite_pattern,
    op_type_rewrite_pattern,
)
from xdsl.dialects import emitc
class CobolBoolTypeConversion(TypeConversionPattern):
    @attr_type_rewrite_pattern
    def convert_type(self, typ: CobolBoolType):
        return i1
class CobolDecimalTypeConversion(TypeConversionPattern):
    @attr_type_rewrite_pattern
    def convert_type(self, type: CobolDecimalType):
        length = type.digits.value.data
        scale = type.scale.value.data
        if scale:
            return Float64Type()
        else:
            if length <= 2:
                return i8 
            elif length <= 4:
                return i16 
            elif length <= 9:
                return i32 
            else:
                return i64

class ConvertDeclareToMemref(RewritePattern):
    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: DeclareOp, rewriter: PatternRewriter):
        occurs = op.attributes["occurs"].value.data
        if occurs == 1:
            return
        elem_type = IntegerType(8)
        alloc_op = AllocOp.get(
            return_type=elem_type,
            shape=[occurs],
        )
        rewriter.replace_op(op, alloc_op)

class CobolStringTypeConversion(TypeConversionPattern):
    @attr_type_rewrite_pattern
    def convert_type(self, type: CobolStringType) -> MemRefType:
        length = type.length.value.data   

        return MemRefType(
            IntegerType(8),  
            [length],       
        )
@dataclass
class ConvertMoveOp(RewritePattern):
    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: MoveOp, rewriter: PatternRewriter):
        src = op.src
        dst = op.dst

        
        dst_type = dst.type
        if not isinstance(dst_type, MemRefType):
            return

        elem_type = dst_type.element_type

        if src.type != elem_type:
            cast_op = ExtSIOp(src, elem_type)
            rewriter.insert_op(cast_op, InsertPoint.before(op))
            src = cast_op.result


        dst_index_attr = op.attributes.get("index")
        if dst_index_attr is None:
            idx_val = 0
        else:
            cobol_idx = dst_index_attr.value.data  
            idx_val = cobol_idx    

        idx_const = EmitC_ConstantOp(IntegerAttr.from_int_and_width(idx_val, IndexType()))
        rewriter.insert_op(idx_const, InsertPoint.before(op))

        store_op = StoreOp.get(src, dst, [idx_const.result])

        rewriter.replace_op(op, store_op)

@dataclass
class ConvertDisplayOp(RewritePattern):
    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: DisplayOp, rewriter: PatternRewriter):
        if len(op.operands) != 1:
            return
        mem = op.operands[0]
        if not isinstance(mem.type, MemRefType):
            return
        idx_attr = op.attributes.get("index")
        if not isinstance(idx_attr, IntegerAttr):
            return
       
        idx_const = EmitC_ConstantOp(IntegerAttr.from_int_and_width(idx_attr.value.data, IndexType()))
        rewriter.insert_op(idx_const)
        
        load = LoadOp.get(mem, [idx_const.result])
        val = load.res

        verbatim = emitc.EmitC_VerbatimOp( 
            StringAttr("std::cout << {};" ),
            [val],
        )
        rewriter.insert_op(load)
        rewriter.insert_op(verbatim)
        rewriter.erase_op(op)

class ConvertCobolToMemrefPass(ModulePass):
    """
    Converts cobol dialect to memref dialect.
    """

    name = "convert_cobol_to_memref"
    def add_includes(self, module: ModuleOp) -> None:
        includes_to_add = []

        for op in module.walk():
            
            if (
                isinstance(op, DisplayOp) or isinstance(op, AcceptOp)
            ) and "iostream" not in includes_to_add:
                includes_to_add.append("iostream")          

        for inc in includes_to_add:
            include_op = emitc.EmitC_IncludeOp(StringAttr(inc), UnitAttr())
            module.body.block.insert_op_before(include_op, module.body.block.first_op)
    def apply(self, ctx: Context, op: ModuleOp) -> None:
        self.add_includes(op)
        PatternRewriteWalker(
            GreedyRewritePatternApplier(
                [
                    CobolBoolTypeConversion(),
                    CobolDecimalTypeConversion(),
                    CobolStringTypeConversion(),
                    ConvertDeclareToMemref(),
                    ConvertMoveOp(),
                    ConvertDisplayOp()
                ]
            ),
            apply_recursively=True,
        ).rewrite_module(op)




def lower_to_memref(module):
    """Lower a COBOL MLIR module to EmitC dialect.

    Args:
        module: The COBOL MLIR module to lower

    Returns:
        The lowered EmitC module
    """

    ConvertCobolToMemrefPass().apply(Context(), module)

    return module
