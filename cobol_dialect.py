from __future__ import annotations

from xdsl.dialects.builtin import IntegerAttr, StringAttr
from xdsl.ir import Dialect, TypeAttribute
from xdsl.irdl import (
    irdl_attr_definition,
    irdl_op_definition,
    IRDLOperation,
    ParameterDef,
    ParametrizedAttribute,
    operand_def,
    prop_def,
    region_def,
    result_def,
)

#===----------------------------------------------------------------------===
# Attribute Definitions
#===----------------------------------------------------------------------===

@irdl_attr_definition
class CobolStringType(ParametrizedAttribute, TypeAttribute):
    """
    A fixed‐length COBOL string type.
    """
    name = "cobol.string"
    length: ParameterDef[IntegerAttr]


@irdl_attr_definition
class CobolDecimalType(ParametrizedAttribute, TypeAttribute):
    """
    A COBOL numeric (decimal) type with total digits and implicit scale.
    """
    name = "cobol.decimal"
    digits: ParameterDef[IntegerAttr]
    scale: ParameterDef[IntegerAttr]


#===----------------------------------------------------------------------===
# Operation Definitions
#===----------------------------------------------------------------------===

@irdl_op_definition
class MoveOp(IRDLOperation):
    """
    Copy a value from src to dst (COBOL MOVE).
    """
    name = "cobol.move"
    src = operand_def()
    dst = operand_def()


@irdl_op_definition
class AddOp(IRDLOperation):
    """
    Numeric addition: result = lhs + rhs.
    """
    name = "cobol.add"
    lhs = operand_def()
    rhs = operand_def()
    result = result_def()


@irdl_op_definition
class CompareOp(IRDLOperation):
    """
    Compare lhs and rhs. 'cond' is one of: \"EQ\", \"LT\", \"GT\".
    Yields an i1 boolean.
    """
    name = "cobol.compare"
    lhs = operand_def()
    rhs = operand_def()
    cond = prop_def(StringAttr)
    result = result_def()

@irdl_op_definition
class DeclareOp(IRDLOperation):
    name = "cobol.declare"
    sym_name = prop_def(StringAttr)
    result   = result_def()

@irdl_op_definition
class IfOp(IRDLOperation):
    """
    Region‐based conditional. 
    First operand is the boolean (from cobol.compare). 
    region_defs are the 'then' and 'else' blocks.
    """
    name = "cobol.if"
    condition = operand_def()
    then_region = region_def()
    else_region = region_def()


@irdl_op_definition
class StopRunOp(IRDLOperation):
    """
    Program termination (COBOL STOP RUN).
    """
    name = "cobol.stop"
    # no operands, no results

@irdl_op_definition
class CobolConstantOp(IRDLOperation):
    """
    A simple constant operation, producing one SSA result of a given type.
    """
    name = "cobol.constant"
    # The literal value: either IntegerAttr or StringAttr
    value = prop_def(StringAttr | IntegerAttr)
    # The single result
    result = result_def()

#===----------------------------------------------------------------------===
# Dialect Registration
#===----------------------------------------------------------------------===

COBOL = Dialect(
    "cobol",
    [
        MoveOp,
        AddOp,
        CompareOp,
        IfOp,
        StopRunOp,
        DeclareOp,
        CobolConstantOp,
    ],
    [
        CobolStringType,
        CobolDecimalType,
    ],
)
