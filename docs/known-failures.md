# Known Failures

Unsupported COBOL features tracked by XFAIL lit tests in `test/cobol_dialect/`.

## Crashes

| Test | COBOL Feature | Root Cause |
|------|---------------|------------|
| `if_no_else` | `IF` without `ELSE` (just `END-IF`) | `IndexError` in `process_cond` — condition parsing fails when comparing a variable to a literal without parenthesized AND/OR |
| `nested_if` | Nested `IF`/`ELSE` inside an `IF` branch | Same `IndexError` in `process_cond` — inner IF triggers the same bare-comparison bug |

Both crashes originate in `src/cobol_front.py:process_cond` which indexes into an empty condition list.

## Silent Drops

These features are parsed by Koopa but have no handler in `xml_handlers.py`, so they are silently ignored during MLIR emission.

| Test | COBOL Feature | What Happens |
|------|---------------|--------------|
| `perform_loop` | `PERFORM N TIMES ... END-PERFORM` | Loop structure ignored; body inlined once |
| `compute_stmt` | `COMPUTE RESULT = A + B` | Entire statement ignored |
| `add_stmt` | `ADD A TO B` | Entire statement ignored |
| `subtract_stmt` | `SUBTRACT B FROM A` | Entire statement ignored |
| `evaluate_stmt` | `EVALUATE ... WHEN ... END-EVALUATE` | Branching ignored; all `WHEN` bodies inlined sequentially |
| `goto_stmt` | `GO TO label` | Jump ignored; all paragraphs inlined sequentially |

## What Would Need to Change

### Condition parsing (`process_cond`)
Fix the `IndexError` when a condition is a simple `VAR > LITERAL` without surrounding `AND`/`OR`/parenthesized sub-expressions. This would unblock `if_no_else` and `nested_if`.

### Arithmetic statements
Add handlers in `xml_handlers.py` for `ADD`, `SUBTRACT`, `MULTIPLY`, `DIVIDE`, and `COMPUTE`. Each needs a corresponding COBOL dialect op (e.g. `cobol.add`, `cobol.sub`) or lowering to existing ops.

### Control flow
- **PERFORM**: Needs a loop op (e.g. `scf.for` or a new `cobol.perform`) and iteration count handling.
- **EVALUATE/WHEN**: Needs branching lowered to a chain of `scf.if` or a switch-like construct.
- **GO TO**: Needs `cf.br` or block-based control flow to model jumps between paragraphs.
