#!/usr/bin/env python3
from __future__ import annotations

from xdsl.dialects.builtin import IntegerAttr, StringAttr, FunctionType
from xdsl.ir            import TypeAttribute, Dialect
from xdsl.irdl import (
    IRDLOperation, irdl_attr_definition, irdl_op_definition,
    ParameterDef, operand_def, var_operand_def,   # ← added
    prop_def, region_def, result_def, ParametrizedAttribute,
)

# ─────────────────────────────────────────────────────────────────────────────
#  Type attributes
# ─────────────────────────────────────────────────────────────────────────────
@irdl_attr_definition
class CobolStringType(ParametrizedAttribute, TypeAttribute):
    name   = "cobol.string"
    length: ParameterDef[IntegerAttr]

@irdl_attr_definition
class CobolDecimalType(ParametrizedAttribute, TypeAttribute):
    name   = "cobol.decimal"
    digits: ParameterDef[IntegerAttr]
    scale:  ParameterDef[IntegerAttr]

# ─────────────────────────────────────────────────────────────────────────────
#  Operation definitions
# ─────────────────────────────────────────────────────────────────────────────
@irdl_op_definition
class MoveOp(IRDLOperation):
    name = "cobol.move"
    src  = operand_def()
    dst  = operand_def()

@irdl_op_definition
class AddOp(IRDLOperation):
    name   = "cobol.add"
    lhs    = operand_def()
    rhs    = operand_def()
    result = result_def()

@irdl_op_definition
class CompareOp(IRDLOperation):
    name   = "cobol.compare"
    lhs    = operand_def()
    rhs    = operand_def()
    cond   = prop_def(StringAttr)
    result = result_def()

@irdl_op_definition
class DeclareOp(IRDLOperation):
    name     = "cobol.declare"
    sym_name = prop_def(StringAttr)
    result   = result_def()

@irdl_op_definition
class IfOp(IRDLOperation):
    name        = "cobol.if"
    condition   = operand_def()
    then_region = region_def()
    else_region = region_def()

@irdl_op_definition
class DisplayOp(IRDLOperation):
    name = "cobol.display"
    args = var_operand_def()

@irdl_op_definition
class StopRunOp(IRDLOperation):
    name = "cobol.stop"

@irdl_op_definition
class CobolConstantOp(IRDLOperation):
    name   = "cobol.constant"
    value  = prop_def(StringAttr | IntegerAttr)
    result = result_def()

@irdl_op_definition
class FuncOp(IRDLOperation):
    name          = "cobol.func"
    sym_name      = prop_def(StringAttr)
    function_type = prop_def(FunctionType)
    body          = region_def("single_block")

# ─────────────────────────────────────────────────────────────────────────────
#  Dialect registration
# ─────────────────────────────────────────────────────────────────────────────
COBOL = Dialect(
    "cobol",
    [
        MoveOp, AddOp, CompareOp, DeclareOp, IfOp,
        DisplayOp, StopRunOp, CobolConstantOp, FuncOp,
    ],
    [CobolStringType, CobolDecimalType],
)
