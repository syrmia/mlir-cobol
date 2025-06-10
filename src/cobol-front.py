#!/usr/bin/env python3
"""
cobol-front.py – tiny COBOL→MLIR translator.
"""

from __future__ import annotations
import sys, re
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


# Regex helpers.
# TODO: Move to `gcobol`.
IDENT = r'[A-Z0-9-]+'
PROGRAM_ID_RE = re.compile(rf'^PROGRAM-ID\.\s*({IDENT})', re.IGNORECASE)
DECL_RE = re.compile(
    rf'^\s*(\d+)\s+({IDENT})\s+PIC\s+([9X]\(\d+\))'
    r'(?:\s+VALUE\s+(".*?"|\S+))?\.?$', re.IGNORECASE)

MOVE_RE    = re.compile(rf'^MOVE\s+(".*?"|{IDENT})\s+TO\s+({IDENT})\.?$', re.IGNORECASE)
ADD_RE     = re.compile(rf'^ADD\s+({IDENT})\s+TO\s+({IDENT})\.?$',         re.IGNORECASE)
IF_RE      = re.compile(rf'^IF\s+({IDENT})\s*([<>=])\s*({IDENT}|\d+)\.?$', re.IGNORECASE)
DISPLAY_RE = re.compile(r'^DISPLAY\s+(.+)$', re.IGNORECASE)
LABEL_RE   = re.compile(rf'^{IDENT}\.$', re.IGNORECASE)

# Tiny parsers.
# TODO: Move to `gcobol`.
def canon(name: str) -> str: return name.upper()

def parse_program_id(lines: List[str]) -> str:
    for l in lines:
        if m := PROGRAM_ID_RE.match(l.strip()): return canon(m.group(1))
    return "MAIN"

def parse_working_storage(lines: List[str]):
    beg = next(i for i,l in enumerate(lines) if 'WORKING-STORAGE SECTION' in l.upper())
    end = next(i for i,l in enumerate(lines) if 'PROCEDURE DIVISION'     in l.upper())
    fields = []
    for l in lines[beg+1:end]:
        if not (m := DECL_RE.match(l.rstrip())): continue
        _, name, pic, val = m.groups()
        if val:
            raw = val.strip()
            if raw.startswith('"') and raw.endswith('"'):
                raw = raw[1:-1]
            val = raw.rstrip('.')
        fields.append({'name': canon(name), 'pic': pic.upper(), 'value': val})
    return fields

def parse_procedure(lines: List[str]):
    idx = next(i for i,l in enumerate(lines) if 'PROCEDURE DIVISION' in l.upper())
    return [l.rstrip() for l in lines[idx+1:] if l.strip()]

# MLIR generation helpers.
I32 = IntegerType(32)
def cobol_string(n:int): return CobolStringType([IntegerAttr(n, I32)])
def cobol_decimal(d:int,s:int=0): return CobolDecimalType([IntegerAttr(d, I32),
                                                           IntegerAttr(s, I32)])

#  Translation.
def translate_to_mlir(name:str, fields, stmts):
    ctx = Context()
    ctx.register_dialect("builtin",lambda c:builtin.Builtin(c))
    ctx.register_dialect("cobol",  lambda c:COBOL)

    mod  = ModuleOp([])
    fn   = FuncOp(attributes={"sym_name":StringAttr(name),
                              "function_type":FunctionType.from_lists([],[])},
                  regions=[builtin.Region(builtin.Block())])
    mod.body.block.add_op(fn)
    body = fn.body.block

    var:dict[str,builtin.Value] = {}

    # Declarations.
    for f in fields:
        n  = int(f['pic'][f['pic'].index('(')+1:-1])
        ty = cobol_string(n) if f['pic'].startswith('X') else cobol_decimal(n)
        decl = DeclareOp(attributes={"sym_name":StringAttr(f['name'])},
                         result_types=[ty])
        body.add_op(decl)
        var[f['name']] = decl.result

        if f['value'] is not None:
            lit = StringAttr(f['value']) if f['pic'].startswith('X') \
                  else IntegerAttr(int(f['value']), I32)
            cst = CobolConstantOp(attributes={"value":lit}, result_types=[ty])
            body.add_op(cst)
            body.add_op(MoveOp(operands=[cst.result, decl.result]))

    # Procedure statements.
    for raw in stmts:
        if LABEL_RE.match(raw.strip()): continue
        s = raw.rstrip('.').strip()

        # DISPLAY
        if m := DISPLAY_RE.match(s):
            toks  = re.findall(r'"[^"]*"|\S+', m.group(1))
            group = []
            for tok in toks:
                if tok.startswith('"'):
                    lit = tok.strip('"')
                    cst = CobolConstantOp(
                        attributes={"value":StringAttr(lit)},
                        result_types=[cobol_string(len(lit))])
                    body.add_op(cst)
                    group.append(cst.result)
                else:
                    group.append(var[canon(tok)])
            body.add_op(DisplayOp(operands=[group]))
            continue

        # MOVE
        if m := MOVE_RE.match(s):
            src_tok,dst_tok = m.groups()
            dst = var[canon(dst_tok)]
            if src_tok.startswith('"'):
                cst = CobolConstantOp(
                    attributes={"value":StringAttr(src_tok.strip('"'))},
                    result_types=[dst.type])
                body.add_op(cst)
                src = cst.result
            else:
                src = var[canon(src_tok)]
            body.add_op(MoveOp(operands=[src,dst]))
            continue

        # ADD
        if m := ADD_RE.match(s):
            src_tok,dst_tok = m.groups()
            add = AddOp(operands=[var[canon(src_tok)],var[canon(dst_tok)]],
                        result_types=[var[canon(dst_tok)].type])
            body.add_op(add)
            var[canon(dst_tok)] = add.result
            continue

        # IF
        if m := IF_RE.match(s):
            lhs_tok,op,rhs_tok = m.groups()
            lhs = var[canon(lhs_tok)]
            if rhs_tok.isdigit():
                cst = CobolConstantOp(attributes={"value":IntegerAttr(int(rhs_tok),I32)},
                                      result_types=[I32])
                body.add_op(cst); rhs = cst.result
            else: rhs = var[canon(rhs_tok)]
            cmp = CompareOp(operands=[lhs,rhs],
                            attributes={"cond":StringAttr({"=":"EQ","<":"LT",">":"GT"}[op])},
                            result_types=[IntegerType(1)])
            body.add_op(cmp)
            body.add_op(IfOp(operands=[cmp.result],
                             regions=[builtin.Region(builtin.Block()),
                                      builtin.Region(builtin.Block())]))
            continue

        # STOP RUN
        if s.upper().startswith("STOP"):
            body.add_op(StopRunOp()); continue

        print("*** unrecognised:", raw, file=sys.stderr)

    return mod

if __name__ == "__main__":
    if len(sys.argv)!=2:
        sys.exit(f"Usage: {sys.argv[0]} program.cbl")
    src   = Path(sys.argv[1])
    lines = src.read_text().splitlines()

    print(translate_to_mlir(parse_program_id(lines),
                            parse_working_storage(lines),
                            parse_procedure(lines)))
