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
from xdsl.dialects.arith import AndIOp, CmpiOp, OrIOp
from xdsl.dialects.scf import IfOp, YieldOp
from xdsl.dialects.builtin import (
    Block, FunctionType, IntAttr, IntegerAttr, IntegerType, ModuleOp, Region, StringAttr
)
from xdsl.ir import OpResult
from xdsl.printer import Printer
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
    StopRunOp,
    SetOp
)
from emitc_lowering import lower_to_emitc
from util.xml_handlers import process_node
import math


# MLIR generation helpers.
I32 = IntegerType(32)
def cobol_string(n: int): return CobolStringType(IntegerAttr(n, I32))
def cobol_decimal(d: int, s: int=0): return CobolDecimalType(IntegerAttr(d, I32), IntegerAttr(s, I32))


def run_koopa(src):
    koopa_path = os.environ.get("KOOPA_PATH", "")
    if koopa_path and not koopa_path.endswith("/"):
        koopa_path += "/"
    koopa_jar = koopa_path + "koopa.jar"

    # Ensure build_xml directory exists
    os.makedirs("build_xml", exist_ok=True)

    subprocess.run([
        "java", "-cp",
        koopa_jar,
        "koopa.app.cli.ToXml",
        "--free-format", src,
        "test/Output/build_xml/" + os.path.splitext(src.name)[0] + ".xml"
    ])


def read_xml(src):
    filename = "test/Output/build_xml/" + os.path.splitext(src.name)[0] + ".xml"
    tree = ET.parse(filename)
    return process_node(tree.getroot())


def process_cond(body, cond):
    if len(cond) == 1:
        if isinstance(cond[0], OpResult):
            return cond[0]

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
        res = process_cond(body, cond[1 : end])
        if end == len(cond) - 1:
            return res
        else:
            cond[end] = res
            return process_cond(body, cond[end: len(cond)])

    for i, tok in enumerate(cond):
        if not isinstance(tok, str):
            continue
        if tok.lower() == "and":
            lhs = process_cond(body, cond[:i])
            rhs = process_cond(body, cond[i + 1:])
            and_op = AndIOp(operand1=lhs, operand2=rhs)
            body.add_op(and_op)
            return and_op.result

    for i, tok in enumerate(cond):
        if not isinstance(tok, str):
            continue
        if tok.lower() == "or":
            lhs = process_cond(body, cond[:i])
            rhs = process_cond(body, cond[i + 1:])
            or_op = OrIOp(operand1=lhs, operand2=rhs)
            body.add_op(or_op)
            return or_op.result

    classes = [
        "alphabetic",
        "negative",
        "numeric"
    ]
    for i, tok in enumerate(cond):
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
                properties={
                    "kind" : StringAttr(kind),
                    "is_positive" : StringAttr(pos)
                },
                result_types=[cobol_decimal(1,1)]
            )
            body.add_op(is_op)
            return is_op.result

    for i, tok in enumerate(cond):
        if tok.lower() == "not":
            expr = process_cond(body, cond[i + 1:])
            not_op = NotOp(
                operands=[expr],
                result_types=[cobol_decimal(1,1)]
            )
            body.add_op(not_op)
            return not_op.result

    for i, tok in enumerate(cond):
        if tok in ("slt", "sle", "sgt", "sge", "eq", "ne"):
            lhs = process_cond(body, cond[:i])
            rhs = process_cond(body, cond[i + 1:])
            cmp_op = CmpiOp(
                operand1=lhs,
                operand2=rhs,
                arg=tok
            )
            body.add_op(cmp_op)
            return cmp_op.result


# dictionary for declared and/or defined vars
# var_name: { value, result }
symbol_table = {}

def processStatements(body, lines, first_run) -> ModuleOp:
    start = 1 if first_run else 0

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

        if operation.get("DISPLAY"):
            arg_list = operation.get("DISPLAY")
            ops = []
            for arg in arg_list:
                type = arg[1]
                if type == "lit":
                    op = ConstantOp(
                        attributes={"value": StringAttr(arg[0])},
                        result_types=[cobol_string(len(arg[0]))]
                    )
                    body.add_op(op)
                    ops.append(op.result)
                else:
                    var = symbol_table[arg[0]]
                    ops.append(var["result"])
            disp_op = DisplayOp(operands=[ops])
            body.add_op(disp_op)
            continue

        elif operation.get("IF"):
            data = operation.get("IF")
            res_cond = process_cond(body, data["cond"])

            else_region = Region(Block()) if data["else"] else None
            ifOp = IfOp(
                cond=res_cond,
                true_region=Region(Block()),
                false_region=else_region,
                return_types=[]
            )
            then_block = ifOp.true_region.block
            processStatements(then_block, data["then"], False)
            then_block.add_op(YieldOp())

            if else_region:
                else_block = ifOp.false_region.block
                processStatements(else_block, data["else"], False)
                else_block.add_op(YieldOp())

            body.add_op(ifOp)
            continue

        elif operation.get("MOVE"):
            data = operation.get("MOVE")
            var_name = data[0]
            raw_value = data[1]

            symbol_table[var_name]["value"] = data[1]

            if isinstance(raw_value, int):
                value =  IntegerAttr(raw_value, I32)
                res = cobol_decimal(raw_value, 0)
            else:
                value = StringAttr(raw_value)
                res = cobol_string(len(raw_value))

            constOp = ConstantOp(
                attributes={"value": value },
                result_types=[res]
            )
            body.add_op(constOp)
            body.add_op(MoveOp(
                operands=[
                    constOp.result,
                    symbol_table[var_name]["result"]
                    ]
                ))
            continue

        elif operation.get("PICTURE"):
            data = operation.get("PICTURE")
            name = data.get("name")
            literal = data.get("literal")
            type = data.get("type")
            length = data.get("length")

            if not literal:
                literal = 0 if type == "num" else ""

            if type == "num":
                for width in (8, 16, 32, 64):
                    if 10**length - 1 < 2**width:
                        decl_value = IntegerAttr(literal, width)
                        break
                res_type = cobol_decimal(length, 0)
            else:
                decl_value = StringAttr(literal)
                res_type = cobol_string(length)

            declOp = DeclareOp(
                attributes={ "value": decl_value },
                result_types=[res_type]
            )
            body.add_op(declOp)

            if literal:
                symbol_table[name] = {
                    "value": literal.strip('\'') if not isinstance(literal, int) else literal,
                    "result": declOp.result
                }
            continue

        elif operation.get("STOP"):
            body.add_op(StopRunOp())
            continue

        else:
            print("Unknown operation: ", operation)
            break


def emit_cobol_mlir(lines):
    ctx = Context()
    ctx.register_dialect("builtin", lambda c: builtin.Builtin(c))
    ctx.register_dialect("cobol", lambda c: COBOL)

    # program-id should always be the first
    prog_id = lines[0]["PROGRAM-ID"]

    module = ModuleOp([])
    fun = FunctionOp(
        attributes={
            "sym_name":StringAttr(prog_id),
            "function_type":FunctionType.from_lists([],[])
        },
        regions=[builtin.Region(builtin.Block())]
    )
    body = fun.body.block
    module.body.block.add_op(fun)

    processStatements(body, lines, True)

    return module




# write partially lowered mlir to file
def write_to_file(filename, module):
    file_path = "out/" + filename + ".mlir"
    with open(file_path, 'w') as file:
        printer = Printer(stream=file)
        printer.print_op(module)

# translation from builtin dialects to llvm dialect
'''
def translate_to_llmv(file_name):
    subprocess.run([
        "xdsl-opt", "out/" + file_name + ".mlir", #"out/mlir_output.mlir",
        "-p" + "printf-to-llvm,convert-memref-to-ptr,convert-ptr-to-llvm",
        "--print-between-passes",
        "-o", "out/" + file_name + "_llvm.mlir" #"out/out_llvm.mlir"
    ])
'''



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
    module = emit_cobol_mlir(lines)

    print(module)

    # xdsl: lowering to emitc dialect
    lower_to_emitc(module)

    print(module)

    # write to file
    file_name = os.path.splitext(Path(sys.argv[1]).name)[0]
    write_to_file(file_name, module)

    # emit llvm dialect
    # translate_to_llmv(file_name)


if __name__ == "__main__":
    main()
