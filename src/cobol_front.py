#!/usr/bin/env python3
"""
cobol-front.py – tiny COBOL→MLIR translator.
"""

from __future__ import annotations
import sys, re, os, subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List

from xdsl.context import Context
from xdsl.dialects import builtin
from xdsl.dialects.builtin import (
    ModuleOp, FunctionType, IntegerType, IntegerAttr, StringAttr
)

from cobol_dialect import (
    COBOL, CobolStringType, CobolDecimalType,
    DeclareOp, CobolConstantOp, MoveOp, AddOp,
    CompareOp, IfOp, DisplayOp, StopRunOp, FuncOp,
)

from util.xml_handlers import process_node

# MLIR generation helpers.
I32 = IntegerType(32)
def cobol_string(n: int): return CobolStringType(IntegerAttr(n, I32))
def cobol_decimal(d: int, s: int=0): return CobolDecimalType(IntegerAttr(d, I32),
                                                           IntegerAttr(s, I32))

def run_koopa(src):
    koopa_path = "/home/ana-marija/Desktop/koopa/"
    # java -cp
    # /home/ana-marija/Desktop/koopa/koopa.jar
    # /home/ana-marija/Desktop/koopa.app.cli.ToXml
    # --free-format test/hello.cbl build_xml/hello.xml
    subprocess.run([
        "java", "-cp",
        koopa_path + "koopa.jar",
        "koopa.app.cli.ToXml",
        "--free-format", src,
        "build_xml/" + os.path.splitext(src.name)[0] + ".xml"
    ])

def read_xml():
    filename = "build_xml/" + os.path.splitext(Path(sys.argv[1]).name)[0] + ".xml"
    tree = ET.parse(filename)
    root = tree.getroot()
    lines = process_node(root)

    return lines

def translate_to_mlir(lines):
    ctx = Context()
    ctx.register_dialect("builtin", lambda c: builtin.Builtin(c))
    ctx.register_dialect("cobol", lambda c: COBOL)

    # program-id should always be the first?
    prog_id = lines[0]["PROGRAM-ID"]

    module = ModuleOp([])
    fun = FuncOp(attributes={"sym_name":StringAttr(prog_id),
                              "function_type":FunctionType.from_lists([],[])},
                  regions=[builtin.Region(builtin.Block())])
    module.body.block.add_op(fun)
    body = fun.body.block

    for i in range(1, len(lines)):
        operation = lines[i]

        if operation.get("DISPLAY"):
            op_const_arg = CobolConstantOp(
                attributes={"value": StringAttr(lines[i].get("DISPLAY").strip("'"))},
                result_types=[cobol_string(len(lines[i].get("DISPLAY")))]
            )

            args = []
            args.append(op_const_arg.result)

            body.add_op(op_const_arg)
            body.add_op(DisplayOp(operands=[args]))
            continue

        elif operation.get("STOP"):
            body.add_op(StopRunOp())
            continue

        else:
            print("Unrecognized operation")
            break

    return module


if __name__ == "__main__":
    # python3 src/main.py test/example.cbl
    if len(sys.argv)!=2:
        sys.exit(f"Usage: {sys.argv[0]} program.cbl")
    src  = Path(sys.argv[1])

    # create xml file
    run_koopa(src)

    # extract lines from xml file
    lines = read_xml()

    print("lines: ", lines)

    module = translate_to_mlir(lines)

    print(module)

    # lowering pass:
    #print(lower_cobol_to_XDSL_pass(module))

