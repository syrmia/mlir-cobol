#!/usr/bin/env python3
"""
cobol-front.py -> tiny COBOL→MLIR translator
"""

from __future__ import annotations
import sys, os, subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from xdsl.context import Context
from xdsl.dialects import builtin
from xdsl.dialects.scf import IfOp, YieldOp
from xdsl.dialects.builtin import (
    Block,
    FloatAttr,
    FunctionType,
    IntegerAttr,
    IntegerType,
    ModuleOp,
    Region,
    StringAttr,
)
from xdsl.ir import OpResult
from xdsl.printer import Printer
from cobol_dialect import (
    COBOL,
    CobolBoolType,
    CobolDecimalType,
    CobolStringType,
    CobolRecordType,
    AcceptOp,
    AddOp,
    AndIOp,
    CmpIOp,
    ConstantOp,
    DeclareOp,
    DisplayOp,
    DivOp,
    ExpOp,
    FunctionOp,
    GotoOp,
    IsOp,
    MoveOp,
    MulOp,
    NotOp,
    OrIOp,
    ParagraphOp,
    PerformOp,
    StopRunOp,
    SetOp,
    StructOp,
    SubOp,
)
from emitc_lowering import lower_to_emitc
from util.xml_handlers import process_node


# MLIR generation helpers.
I32 = IntegerType(32)


def cobol_bool():
    return CobolBoolType()


def cobol_string(n: int):
    return CobolStringType(IntegerAttr(n, I32))


def cobol_decimal(d: int, s: int = 0):
    return CobolDecimalType(IntegerAttr(d, I32), IntegerAttr(s, I32))


def cobol_record(name: str):
    return CobolRecordType(StringAttr(name))


def run_koopa(src):
    koopa_path = os.environ.get("KOOPA_PATH", "")
    if koopa_path and not koopa_path.endswith("/"):
        koopa_path += "/"
    koopa_jar = koopa_path + "koopa.jar"

    # Ensure build_xml directory exists
    os.makedirs("build_xml", exist_ok=True)

    subprocess.run(
        [
            "java",
            "-cp",
            koopa_jar,
            "koopa.app.cli.ToXml",
            "--free-format",
            src,
            "test/Output/build_xml/" + os.path.splitext(src.name)[0] + ".xml",
        ]
    )


def read_xml(src):
    filename = "test/Output/build_xml/" + os.path.splitext(src.name)[0] + ".xml"
    tree = ET.parse(filename)
    return process_node(tree.getroot())


def process_cond(body, cond):
    if len(cond) == 1:
        if isinstance(cond[0], OpResult):
            return cond[0]

        # Handle literal tuples produced by extractConditionTokens
        if isinstance(cond[0], tuple):
            lit_kind, lit_val = cond[0]
            if lit_kind == "lit_int":
                for width in (8, 16, 32, 64):
                    if lit_val < 2**width:
                        value = IntegerAttr(lit_val, width)
                        break
                res_type = cobol_decimal(len(str(lit_val)), 0)
            elif lit_kind == "lit_float":
                value = FloatAttr(lit_val, 64)
                res_type = cobol_decimal(7, 2)
            elif lit_kind == "lit_str":
                value = StringAttr(lit_val)
                res_type = cobol_string(len(lit_val))
            else:
                raise ValueError(f"Unknown literal kind in condition: {lit_kind}")
            const_op = ConstantOp(attributes={"value": value}, result_types=[res_type])
            body.add_op(const_op)
            return const_op.result

        var = symbol_table[cond[0]]
        res = var["result"]
        return res

    def find_matching_paren(start, l):
        depth = 0
        for i in range(start, len(l)):
            if l[i] == "(":
                depth += 1
            elif l[i] == ")":
                depth -= 1
                if depth == 0:
                    return i
        return -1

    if cond[0] == "(":
        end = find_matching_paren(0, cond)
        res = process_cond(body, cond[1:end])
        if end == len(cond) - 1:
            return res
        else:
            cond[end] = res
            return process_cond(body, cond[end : len(cond)])

    for i, tok in enumerate(cond):
        if not isinstance(tok, str):
            continue
        if tok.lower() == "and":
            lhs = process_cond(body, cond[:i])
            rhs = process_cond(body, cond[i + 1 :])
            and_op = AndIOp(operands=[lhs, rhs], result_types=[cobol_bool()])
            body.add_op(and_op)
            return and_op.result

    for i, tok in enumerate(cond):
        if not isinstance(tok, str):
            continue
        if tok.lower() == "or":
            lhs = process_cond(body, cond[:i])
            rhs = process_cond(body, cond[i + 1 :])
            or_op = OrIOp(operands=[lhs, rhs], result_types=[cobol_bool()])
            body.add_op(or_op)
            return or_op.result

    classes = ["alphabetic", "negative", "numeric"]
    for i, tok in enumerate(cond):
        if not isinstance(tok, str):
            continue
        if tok.lower() == "is":
            expr = symbol_table[cond[i - 1]]["result"]
            if cond[i + 1] == "not":
                pos = "false"
                kind = cond[i + 2] if i < len(cond) - 2 else None
            else:
                pos = "true"
                kind = cond[i + 1] if i < len(cond) - 1 else None
            is_op = IsOp(
                operands=[expr],
                properties={"kind": StringAttr(kind), "is_positive": StringAttr(pos)},
                result_types=[cobol_bool()],
            )
            body.add_op(is_op)
            return is_op.result

    for i, tok in enumerate(cond):
        if not isinstance(tok, str):
            continue
        if tok.lower() == "not":
            expr = process_cond(body, cond[i + 1 :])
            not_op = NotOp(operands=[expr], result_types=[cobol_decimal(1, 1)])
            body.add_op(not_op)
            return not_op.result

    for i, tok in enumerate(cond):
        if not isinstance(tok, str):
            continue
        comp_operators = ["eq", "ne", "slt", "sle", "sgt", "sge"]
        if tok in comp_operators:
            lhs = process_cond(body, cond[:i])
            rhs = process_cond(body, cond[i + 1 :])
            cmp_op = CmpIOp(
                operands=[lhs, rhs],
                result_types=[cobol_bool()],
                properties={
                    "predicate": IntegerAttr.from_int_and_width(
                        comp_operators.index(tok), 8
                    )
                },
            )
            body.add_op(cmp_op)
            return cmp_op.result


def process_expression(body, expression):
    if len(expression) == 1:
        if isinstance(expression[0], OpResult):
            return expression[0]

        var = symbol_table[expression[0]]
        res = var["result"]
        return res

    def find_matching_paren(start, l):
        depth = 0
        for i in range(start, len(l)):
            if l[i] == "(":
                depth += 1
            elif l[i] == ")":
                depth -= 1
                if depth == 0:
                    return i
        return -1

    if expression[0] == "(":
        end = find_matching_paren(0, expression)
        res = process_expression(body, expression[1:end])
        if end == len(expression) - 1:
            return res
        else:
            expression[end] = res
            return process_expression(body, expression[end : len(expression)])

    for i, tok in enumerate(expression):
        if not isinstance(tok, str):
            continue
        if tok.lower() == "+":
            lhs = process_expression(body, expression[:i])
            rhs = process_expression(body, expression[i + 1 :])
            add_op = AddOp(operands=[lhs, rhs], result_types=[cobol_decimal(2, 0)], properties={"kind": StringAttr("compute")})
            body.add_op(add_op)
            return add_op.result

    for i, tok in enumerate(expression):
        if not isinstance(tok, str):
            continue
        if tok.lower() == "*":
            lhs = process_expression(body, expression[:i])
            rhs = process_expression(body, expression[i + 1 :])
            mul_op = MulOp(operands=[lhs, rhs], result_types=[cobol_decimal(2, 0)], properties={"kind": StringAttr("compute")})
            body.add_op(mul_op)
            return mul_op.result

    for i, tok in enumerate(expression):
        if not isinstance(tok, str):
            continue
        if tok.lower() == "-":
            lhs = process_expression(body, expression[:i])
            rhs = process_expression(body, expression[i + 1 :])
            sub_op = SubOp(operands=[lhs, rhs], result_types=[cobol_decimal(2, 0)], properties={"kind": StringAttr("compute")})
            body.add_op(sub_op)
            return sub_op.result

    for i, tok in enumerate(expression):
        if not isinstance(tok, str):
            continue
        if tok.lower() == "/":
            lhs = process_expression(body, expression[:i])
            rhs = process_expression(body, expression[i + 1 :])
            div_op = DivOp(operands=[lhs, rhs], result_types=[cobol_decimal(2, 0)], properties={"kind": StringAttr("compute")})
            body.add_op(div_op)
            return div_op.result

    for i, tok in enumerate(expression):
        if not isinstance(tok, str):
            continue
        if tok.lower() == "**":
            lhs = process_expression(body, expression[:i])
            rhs = process_expression(body, expression[i + 1 :])
            exp_op = ExpOp(operands=[lhs, rhs], result_types=[cobol_decimal(2, 0)], properties={"kind": StringAttr("compute")})
            body.add_op(exp_op)
            return exp_op.result


# dictionary for declared and/or defined vars
# var_name: { value, result }
symbol_table = {}


# def process_statements(body: Block, lines: any, first_run: bool, module_ops: any = None) -> ModuleOp:
def process_statements(body: Block, lines: any, first_run: bool) -> ModuleOp:
    start = 1 if first_run else 0

    # for group item declarations
    # {level, body}
    struct_regions_stack = []

    for i in range(start, len(lines)):
        operation = lines[i]

        if not operation:
            print("Operation: NULL")
            break

        if operation.get("ACCEPT"):
            var = operation.get("ACCEPT")
            target = symbol_table[var]["result"]
            op = AcceptOp(operands=[target])
            body.add_op(op)
            continue

        elif operation.get("ADD"):
            vars = operation.get("ADD")
            lhs = symbol_table[vars[0]]["result"]
            rhs = symbol_table[vars[1]]["result"]
            res_type = symbol_table[vars[1]]["result"].type
            op = AddOp(operands={lhs, rhs}, result_types=[res_type], properties={"kind": StringAttr("add_to")})
            body.add_op(op)
            continue

        elif operation.get("COMPUTE"):
            expression = operation.get("COMPUTE")
            res_var = expression[1]
            expr_res = process_expression(body, expression[expression.index('=') + 1:])
            src = expr_res
            dst = symbol_table[res_var]["result"]
            body.add_op(MoveOp(operands=[src, dst]))
            continue

        elif operation.get("DISPLAY"):
            arg_list = operation.get("DISPLAY")
            ops = []
            for arg in arg_list:
                type = arg[1]
                if type == "lit":
                    op = ConstantOp(
                        attributes={"value": StringAttr(arg[0])},
                        result_types=[cobol_string(len(arg[0]))],
                    )
                    body.add_op(op)
                    ops.append(op.result)
                else:
                    var = symbol_table[arg[0]]
                    ops.append(var["result"])
            disp_op = DisplayOp(operands=[ops])
            body.add_op(disp_op)
            continue

        elif operation.get("DIV"):
            vars = operation.get("DIV")
            lhs = symbol_table[vars[0]]["result"]
            rhs = symbol_table[vars[1]]["result"]
            res_type = symbol_table[vars[1]]["result"].type
            op = DivOp(operands={lhs, rhs}, result_types=[res_type], properties={"kind": StringAttr("div_into")})
            body.add_op(op)
            continue

        elif operation.get("IF"):
            data = operation.get("IF")
            res_cond = process_cond(body, data["cond"])

            else_region = Region(Block()) if data["else"] else None
            ifOp = IfOp(
                cond=res_cond,
                true_region=Region(Block()),
                false_region=else_region,
                return_types=[],
            )
            then_block = ifOp.true_region.block
            process_statements(then_block, data["then"], False)
            then_block.add_op(YieldOp())

            if else_region:
                else_block = ifOp.false_region.block
                process_statements(else_block, data["else"], False)
                else_block.add_op(YieldOp())

            body.add_op(ifOp)
            continue

        elif operation.get("PERFORM"):
            data = operation.get("PERFORM")
            times_val = data["times"]
            loop_body_stmts = data["body"]

            # Create a constant for the iteration count
            if isinstance(times_val, int):
                for width in (8, 16, 32, 64):
                    if times_val < 2**width:
                        times_attr = IntegerAttr(times_val, width)
                        break
                times_const = ConstantOp(
                    attributes={"value": times_attr},
                    result_types=[cobol_decimal(len(str(times_val)), 0)],
                )
                body.add_op(times_const)
                times_result = times_const.result
            else:
                # variable reference
                times_result = symbol_table[times_val]["result"]

            # Build the loop body region
            loop_region = Region(Block())
            loop_block = loop_region.block
            process_statements(loop_block, loop_body_stmts, False)

            perform_op = PerformOp(
                operands=[times_result],
                regions=[loop_region],
            )
            body.add_op(perform_op)
            continue

        elif operation.get("EVALUATE"):
            data = operation.get("EVALUATE")
            subject_name = data["subject"]
            cases = data["cases"]

            subject_result = symbol_table[subject_name]["result"]

            # Build a chain of nested scf.if for each WHEN case
            def build_evaluate_chain(target_body, case_idx):
                if case_idx >= len(cases):
                    return
                case = cases[case_idx]

                if case["other"]:
                    # WHEN OTHER — just emit the statements directly
                    process_statements(target_body, case["stmts"], False)
                    return

                # Create comparison: subject == value
                val = case["value"]
                if isinstance(val, int):
                    for width in (8, 16, 32, 64):
                        if val < 2**width:
                            val_attr = IntegerAttr(val, width)
                            break
                    val_const = ConstantOp(
                        attributes={"value": val_attr},
                        result_types=[cobol_decimal(len(str(val)), 0)],
                    )
                    target_body.add_op(val_const)
                    rhs = val_const.result
                elif isinstance(val, str):
                    val_const = ConstantOp(
                        attributes={"value": StringAttr(val)},
                        result_types=[cobol_string(len(val))],
                    )
                    target_body.add_op(val_const)
                    rhs = val_const.result
                else:
                    return

                cmp_op = CmpIOp(
                    operands=[subject_result, rhs],
                    result_types=[cobol_bool()],
                    properties={
                        "predicate": IntegerAttr.from_int_and_width(0, 8)  # eq
                    },
                )
                target_body.add_op(cmp_op)

                # Build then region
                then_region = Region(Block())
                then_block = then_region.block
                process_statements(then_block, case["stmts"], False)
                then_block.add_op(YieldOp())

                # Build else region with remaining cases (recursive)
                else_region = Region(Block())
                else_block = else_region.block
                build_evaluate_chain(else_block, case_idx + 1)
                else_block.add_op(YieldOp())

                ifOp = IfOp(
                    cond=cmp_op.result,
                    true_region=then_region,
                    false_region=else_region,
                    return_types=[],
                )
                target_body.add_op(ifOp)

            build_evaluate_chain(body, 0)
            continue

        elif operation.get("GOTO"):
            target_label = operation.get("GOTO")
            goto_op = GotoOp(
                properties={"target": StringAttr(target_label)},
            )
            body.add_op(goto_op)
            continue

        elif operation.get("PARAGRAPH"):
            para_name = operation.get("PARAGRAPH")
            para_region = Region(Block())
            para_op = ParagraphOp(
                properties={"sym_name": StringAttr(para_name)},
                regions=[para_region],
            )
            body.add_op(para_op)
            continue

        elif operation.get("MOVE"):
            data = operation.get("MOVE")

            data_dst = data[0]
            data_src = data[1]

            if isinstance(data_src, int):
                for width in (8, 16, 32, 64):
                    if data_src - 1 < 2**width:
                        value = IntegerAttr(data_src, width)
                        break
                res = cobol_decimal(len(str(data_src)), 0)

            elif data_src in symbol_table:
                symbol_table[data_dst]["value"] = data_src
                sym_value = symbol_table[data_src]["value"]

                if isinstance(sym_value, int):
                    for width in (8, 16, 32, 64):
                        if sym_value - 1 < 2**width:
                            value = IntegerAttr(sym_value, width)
                            break
                    res = cobol_decimal(len(str(sym_value)), 0)
                else:
                    value = StringAttr(sym_value)
                    res = cobol_string(len(sym_value))

            else:  # type[src] = string
                value = StringAttr(data_src)
                res = cobol_string(len(data_src))

            constOp = ConstantOp(attributes={"value": value}, result_types=[res])
            body.add_op(constOp)
            src = constOp.result
            dst = symbol_table[data_dst]["result"]
            body.add_op(MoveOp(operands=[src, dst]))
            continue

        elif operation.get("MUL"):
            vars = operation.get("MUL")
            lhs = symbol_table[vars[0]]["result"]
            rhs = symbol_table[vars[1]]["result"]
            res_type = symbol_table[vars[1]]["result"].type
            op = MulOp(operands={lhs, rhs}, result_types=[res_type], properties={"kind": StringAttr("mul_by")})
            body.add_op(op)
            continue

        elif operation.get("PICTURE"):
            data = operation.get("PICTURE")
            name = data.get("name")
            literal = data.get("literal")
            type = data.get("type")
            length = data.get("length")
            level = int(data.get("level"))

            # for floats:
            int_part = data.get("int_part")
            frac_part = data.get("frac_part")

            def get_float_type(digits: int) -> int:
                if digits <= 4:
                    return 16
                if digits <= 7:
                    return 32
                return 64

            if not literal:
                literal = 0 if type == "int" or type == "float" else ""

            if type == "int":
                for width in (8, 16, 32, 64):
                    if 10**length - 1 < 2**width:
                        decl_value = IntegerAttr(literal, width)
                        break
                res_type = cobol_decimal(length, 0)
            elif type == "alpha" or type == "alnum":
                decl_value = StringAttr(literal)
                res_type = cobol_string(length)
            elif type == "float":
                total_digits = int_part + frac_part
                float_type = get_float_type(total_digits)
                decl_value = FloatAttr(literal, float_type)
                res_type = cobol_decimal(int_part, frac_part)
            else:
                # unknown type
                pass

            declOp = DeclareOp(
                attributes={"value": decl_value, "level": IntegerAttr(int(level), 8)},
                result_types=[res_type],
            )

            while struct_regions_stack and int(level) <= int(
                struct_regions_stack[-1][0]
            ):
                struct_regions_stack.pop()

            if struct_regions_stack:
                struct_regions_stack[-1][1].block.add_op(declOp)
            else:
                body.add_op(declOp)

            if literal:
                symbol_table[name] = {
                    "value": (
                        literal.strip("'")
                        if not isinstance(literal, int | float)
                        else literal
                    ),
                    "result": declOp.result,
                }
            else:
                symbol_table[name] = {"value": None, "result": declOp.result}
            continue

        elif operation.get("STRUCT"):
            op_data = operation.get("STRUCT")
            name = op_data.get("name")
            level = op_data.get("level")

            struct_body = Region(Block())

            res_type = cobol_record(name)

            structOp = StructOp(
                attributes={"struct_name": StringAttr(name)},
                regions={struct_body},
                result_types=[res_type],
            )

            while struct_regions_stack and int(level) <= int(
                struct_regions_stack[-1][0]
            ):
                struct_regions_stack.pop()

            if struct_regions_stack:
                struct_regions_stack[-1][1].block.add_op(structOp)
            else:
                # module_ops.append(structOp)
                body.add_op(structOp)

            symbol_table[name] = {"value": None, "result": structOp.result}
            struct_regions_stack.append([op_data.get("level"), struct_body])
            continue

        elif operation.get("STOP"):
            body.add_op(StopRunOp())
            continue

        elif operation.get("SUB"):
            vars = operation.get("SUB")
            lhs = symbol_table[vars[0]]["result"]
            rhs = symbol_table[vars[1]]["result"]
            res_type = symbol_table[vars[1]]["result"].type
            sub_op = SubOp(operands={lhs, rhs}, result_types=[res_type], properties={"kind": StringAttr("sub_from")})
            body.add_op(sub_op)
            continue

        else:
            print("Unknown operation: ", operation)
            break


def emit_cobol_dialect(lines):
    ctx = Context()
    ctx.register_dialect("builtin", lambda c: builtin.Builtin(c))
    ctx.register_dialect("cobol", lambda c: COBOL)

    # program-id should always be the first
    prog_id = lines[0]["PROGRAM-ID"]

    module = ModuleOp([])
    fun = FunctionOp(
        attributes={
            "sym_name": StringAttr(prog_id),
            "function_type": FunctionType.from_lists([], []),
        },
        regions=[builtin.Region(builtin.Block())],
    )
    body = fun.body.block
    module.body.block.add_op(fun)

    # For top-lvl declarations: structs and functions
    # module_ops = []

    process_statements(body, lines, True)
    # process_statements(body, lines, True, module_ops)

    # module_ops.append(fun)

    # for op in module_ops:
    #    module.body.block.add_op(op)

    return module


# write partially lowered mlir to file
def write_to_file(filename, module):
    file_path = "out/" + filename + ".mlir"
    with open(file_path, "w") as file:
        printer = Printer(stream=file)
        printer.print_op(module)


def main():
    """Main entry point for cobol-front."""
    if len(sys.argv) != 2:
        sys.exit(f"Usage: {sys.argv[0]} program.cbl")
    src = Path(sys.argv[1])

    # parser: create xml file
    run_koopa(src)

    # xml: extract lines from xml file
    lines = read_xml(src)

    # xdsl: translate to cobol dialect
    module = emit_cobol_dialect(lines)
    print(module)

    # xdsl: lowering to emitc dialect
    lower_to_emitc(module)
    print(module)

    # write to file
    file_name = os.path.splitext(Path(sys.argv[1]).name)[0]
    write_to_file(file_name, module)


if __name__ == "__main__":
    main()
