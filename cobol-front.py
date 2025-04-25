#!/usr/bin/env python3
import sys
import re

from xdsl.context import Context
from xdsl.ir import Region, Block
from xdsl.dialects import builtin
from xdsl.dialects.builtin import ModuleOp, IntegerType, IntegerAttr, StringAttr
from cobol_dialect import (
    COBOL,
    DeclareOp,
    MoveOp,
    AddOp,
    CompareOp,
    IfOp,
    StopRunOp,
    CobolStringType,
    CobolDecimalType,
    CobolConstantOp,
)

# Regex for working-storage DECL
DECL_RE = re.compile(
    r'^\s*(\d+)\s+(\w+)\s+PIC\s+([9X]\(\d+\))'
    r'(?:\s+VALUE\s+(".*?"|\S+))?',
    re.IGNORECASE
)

# Regex for MOVE statements (handles quoted or unquoted source)
MOVE_RE = re.compile(
    r'^MOVE\s+(".*?"|\w+)\s+TO\s+(\w+)$',
    re.IGNORECASE
)

# Regex for ADD statements: ADD SRC TO DST
ADD_RE = re.compile(r'^ADD\s+(\w+)\s+TO\s+(\w+)$', re.IGNORECASE)

# Regex for IF statements: IF LHS (> | < | =) RHS
IF_RE = re.compile(r'^IF\s+(\w+)\s*([<>=])\s*(\w+|\d+)$', re.IGNORECASE)

def parse_working_storage(lines):
    start = next(i for i, l in enumerate(lines) if 'WORKING-STORAGE SECTION' in l)
    end   = next(i for i, l in enumerate(lines) if 'PROCEDURE DIVISION'   in l)
    ws    = lines[start+1:end]

    fields = []
    for l in ws:
        m = DECL_RE.match(l)
        if not m:
            continue
        lvl, name, pic, val = m.groups()
        if val:
            # strip quotes and trailing dot
            val = val.strip().lstrip('"').rstrip('"').rstrip('.')
        fields.append({'name': name, 'pic': pic, 'value': val or None})
    return fields

def parse_procedure(lines):
    idx = next(i for i, l in enumerate(lines) if 'PROCEDURE DIVISION' in l)
    # return raw statements (we’ll regex-parse them below)
    return [l.strip() for l in lines[idx+1:] if l.strip()]

def translate_to_cobol_mlir(fields, stmts):
    # 1) Context + dialects
    ctx = Context()
    ctx.register_dialect("builtin", builtin)
    ctx.register_dialect("cobol", COBOL)

    # 2) Module + entry block
    module = ModuleOp([])
    entry  = module.regions[0].block
    var_map = {}

    decl_type = None

    # 3) Declare & init WORKING-STORAGE
    for f in fields:
        name, pic = f['name'], f['pic']
        # choose COBOL type
        if pic.startswith('X'):
            length = int(pic[pic.index('(')+1:-1])
            ty = CobolStringType([IntegerAttr(length, IntegerType(32))])
        else:
            digits = int(pic[pic.index('(')+1:-1])
            ty = CobolDecimalType([
                IntegerAttr(digits, IntegerType(32)),
                IntegerAttr(0,      IntegerType(32))
            ])

        # DeclareOp
        decl = DeclareOp(
            attributes={'sym_name': StringAttr(name)},
            result_types=[ty],
        )
        entry.add_op(decl)
        var_map[name] = decl.result
        decl_type = ty  # remember for ADD

        # initial VALUE (if any)
        if f['value'] is not None:
            lit_attr = (
                StringAttr(f['value']) 
                if pic.startswith('X') 
                else IntegerAttr(int(f['value']), IntegerType(32))
            )
            const = CobolConstantOp(
                attributes={'value': lit_attr},
                result_types=[ty],
            )
            entry.add_op(const)
            entry.add_op(
                MoveOp(operands=[const.result, var_map[name]])
            )

    # 4) Lower PROCEDURE DIVISION
    for stmt in stmts:
        # Try MOVE
        m = MOVE_RE.match(stmt)
        if m:
            src_tok, dst = m.groups()
            if src_tok.startswith('"'):
                # literal string → constant
                lit = src_tok.strip('"')
                const = CobolConstantOp(
                    attributes={'value': StringAttr(lit)},
                    result_types=[decl_type],
                )
                entry.add_op(const)
                src_val = const.result
            else:
                src_val = var_map[src_tok]
            entry.add_op(
                MoveOp(operands=[src_val, var_map[dst]])
            )
            continue

        # Try ADD
        m = ADD_RE.match(stmt)
        if m:
            src, dst = m.groups()
            add = AddOp(
                operands=[var_map[src], var_map[dst]],
                result_types=[decl_type],
            )
            entry.add_op(add)
            var_map[dst] = add.result
            continue

        # Try IF
        m = IF_RE.match(stmt)
        if m:
            lhs, cmpop, rhs_tok = m.groups()
            # RHS constant or variable
            if rhs_tok.isdigit():
                rhs_const = CobolConstantOp(
                    attributes={'value': IntegerAttr(int(rhs_tok), IntegerType(32))},
                    result_types=[IntegerType(32)],
                )
                entry.add_op(rhs_const)
                rhs_val = rhs_const.result
            else:
                rhs_val = var_map[rhs_tok]

            cond_map = {'>':'GT','<':'LT','=':'EQ'}
            cmp = CompareOp(
                operands=[var_map[lhs], rhs_val],
                attributes={'cond': StringAttr(cond_map[cmpop])},
                result_types=[IntegerType(1)],
            )
            entry.add_op(cmp)

            # stub regions
            then_r = Region(Block())
            else_r = Region(Block())
            entry.add_op(
                IfOp(operands=[cmp.result], regions=[then_r, else_r])
            )
            continue

        # Try STOP RUN
        if stmt.upper().startswith('STOP'):
            entry.add_op(StopRunOp())
            continue

        # unrecognized statement
        print(f"Warning: couldn’t parse statement: {stmt}", file=sys.stderr)

    return module

def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <test.cbl>", file=sys.stderr)
        sys.exit(1)

    lines  = open(sys.argv[1]).read().splitlines()
    fields = parse_working_storage(lines)
    stmts  = parse_procedure(lines)
    module = translate_to_cobol_mlir(fields, stmts)
    print(module)

if __name__ == "__main__":
    main()
