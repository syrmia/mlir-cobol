#!/usr/bin/env python3
from __future__ import annotations

from xdsl.dialects.builtin import FunctionType, IntegerAttr, StringAttr
from xdsl.ir import Dialect, TypeAttribute
from xdsl.irdl import (
    irdl_attr_definition,
    irdl_op_definition,
    IRDLOperation,
    operand_def,
    ParametrizedAttribute,
    prop_def,
    region_def,
    result_def,
    var_operand_def
)

# ─────────────────────────────────────────────────────────────────────────────
#  Type attributes
# ─────────────────────────────────────────────────────────────────────────────
@irdl_op_definition
class FunctionOp(IRDLOperation):
    name          = "cobol.func"
    sym_name      = prop_def(StringAttr)
    function_type = prop_def(FunctionType)
    body          = region_def("single_block")

@irdl_attr_definition
class CobolStringType(ParametrizedAttribute, TypeAttribute):
    name   = "cobol.string"
    length: IntegerAttr

@irdl_attr_definition
class CobolDecimalType(ParametrizedAttribute, TypeAttribute):
    name   = "cobol.decimal"
    digits: IntegerAttr
    scale:  IntegerAttr

# ─────────────────────────────────────────────────────────────────────────────
#  Operation definitions
# ─────────────────────────────────────────────────────────────────────────────
@irdl_op_definition
class AcceptOp(IRDLOperation):
    name     = "cobol.accept"
    args = operand_def(StringAttr)

@irdl_op_definition
class AddOp(IRDLOperation):
    name   = "cobol.add"
    lhs    = operand_def()
    rhs    = operand_def()
    result = result_def()

@irdl_op_definition
class ConstantOp(IRDLOperation):
    name   = "cobol.constant"
    value  = prop_def(StringAttr | IntegerAttr)
    result = result_def()

@irdl_op_definition
class DeclareOp(IRDLOperation):
    name     = "cobol.declare"
    sym_name = prop_def(StringAttr)
    result   = result_def()

@irdl_op_definition
class DisplayOp(IRDLOperation):
    name = "cobol.display"
    args = var_operand_def()

@irdl_op_definition
class IsOp(IRDLOperation):
    name = "cobol.is"
    var  = operand_def()
    kind = prop_def(StringAttr)
    is_positive = prop_def(StringAttr)
    result = result_def()

@irdl_op_definition
class MoveOp(IRDLOperation):
    name = "cobol.move"
    src  = operand_def()
    dst  = operand_def()

@irdl_op_definition
class NotOp(IRDLOperation):
    name = "cobol.not"
    op = operand_def()
    result = result_def()

@irdl_op_definition
class SetOp(IRDLOperation):
    name     = "cobol.set"
    sym_name = prop_def(StringAttr)
    result = result_def()

@irdl_op_definition
class StopRunOp(IRDLOperation):
    name = "cobol.stop"

# ─────────────────────────────────────────────────────────────────────────────
#  Dialect registration
# ─────────────────────────────────────────────────────────────────────────────
COBOL = Dialect(
    "cobol",
    [
        AcceptOp,
        AddOp,
        ConstantOp,
        DeclareOp,
        DisplayOp,
        FunctionOp,
        IsOp,
        MoveOp,
        StopRunOp,
        SetOp
    ],
    [
        CobolStringType,
        CobolDecimalType
    ],
)
