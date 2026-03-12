# Known Failures

Unsupported COBOL features tracked by XFAIL lit tests in `test/cobol_dialect/`.

## Crashes

**None at this time.**

Previously, `if_no_else` and `nested_if` crashed with an `IndexError` in
`process_cond` when comparing a variable to a literal without parenthesized
AND/OR.  This was fixed by correcting condition parsing in `cobol_front.py`.

## Silent Drops

**None at this time.**

Previously, `perform_loop`, `evaluate_stmt`, and `goto_stmt` were silently
ignored because `xml_handlers.py` lacked handlers for PERFORM, EVALUATE, and
GO TO.  Handlers have been added and EmitC lowering patterns
(`ConvertPerformOp`, `ConvertParagraphOp`, `ConvertGotoOp`) now generate valid
C++ through `emitc.verbatim`.

## What Would Need to Change

### Arithmetic statements
Add handlers in `xml_handlers.py` for `ADD`, `SUBTRACT`, `MULTIPLY`, `DIVIDE`, and `COMPUTE`. Each needs a corresponding COBOL dialect op (e.g. `cobol.add`, `cobol.sub`) or lowering to existing ops.
