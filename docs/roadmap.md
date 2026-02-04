# Semantic Equivalence Analysis — Implementation Roadmap

This roadmap describes the incremental build plan for `cobol-equiv`, the semantic equivalence checker for the mlir-cobol project. Each phase produces a usable, testable increment.

## Phase 1: Normalization and IR Parsing

**Goal**: Get both C++ programs into a normalized LLVM IR form and parse it into Python data structures. This is the foundation everything else builds on.

### Tasks

1. **`normalize.py`** — LLVM IR normalization module
   - Invoke `clang -S -emit-llvm -O0 input.cpp -o output.ll` to compile C++ to LLVM IR
   - Invoke `opt -passes='mem2reg,instcombine,simplifycfg,dce,reassociate' input.ll -o output.ll` to canonicalize
   - Handle subprocess errors, missing tools, and temporary file management
   - Auto-detect `clang` and `opt` paths (check `$PATH`, common install locations)

2. **`ir_parser.py`** — LLVM IR text parser
   - Parse LLVM IR textual format into Python dataclasses:
     - `Module`: list of functions and global declarations
     - `Function`: name, parameter list, return type, list of basic blocks
     - `BasicBlock`: label, list of instructions
     - `Instruction`: opcode, operands, result SSA name, type info, metadata
   - Handle the subset of LLVM IR that Clang generates for the kind of C++ we produce:
     - Arithmetic: `add`, `sub`, `mul`, `sdiv`, `srem`
     - Comparison: `icmp` with predicates
     - Control flow: `br`, `ret`, `switch`
     - Memory: `alloca`, `load`, `store` (before mem2reg), `getelementptr`
     - Calls: `call` (for `std::cout`, `std::cin`, and other library functions)
     - Type casts: `sext`, `zext`, `trunc`, `bitcast`
     - SSA: `phi` nodes (after mem2reg)
     - Select: `select` (conditional value)
   - Provide a clean API: `module = parse_llvm_ir("path/to/file.ll")`

3. **Tests for Phase 1**
   - Unit tests: parse known LLVM IR snippets, verify data structures
   - Integration test: compile a simple C++ file, normalize, parse, verify round-trip

### Deliverables

- `src/semantic_equiv/__init__.py`
- `src/semantic_equiv/normalize.py`
- `src/semantic_equiv/ir_parser.py`
- `test/semantic_equiv/test_normalize.py`
- `test/semantic_equiv/test_ir_parser.py`

### External Dependencies

- `clang` (C++ to LLVM IR compilation)
- `opt` (LLVM IR optimization / normalization)
- Both are part of a standard LLVM/Clang installation

---

## Phase 2: Static Semantic Fingerprinting

**Goal**: Extract semantic features from parsed LLVM IR and compute a similarity score between two programs. This gives an immediate, fast comparison capability.

### Tasks

1. **Feature extractors** in `fingerprint.py`:
   - **I/O sequence extractor**: Walk the IR and collect all `call` instructions to I/O functions (`operator<<` on `std::cout`, `operator>>` on `std::cin`). Record the order and the type of each operand. Produce an ordered list of I/O operations.
   - **Operation histogram**: Count occurrences of each opcode (`add`, `mul`, `icmp`, `br`, `call`, etc.) per function. Represent as a frequency vector.
   - **CFG shape extractor**: Build a control flow graph from basic blocks and branch instructions. Extract properties: number of nodes, edges, back-edges (loops), nesting depth, dominator tree shape.
   - **Computation DAG extractor**: Build a data-dependency graph from SSA def-use chains. Track how input values flow through operations to output values.
   - **Type signature extractor**: Collect function parameter types, return type, and local variable types.

2. **Comparison functions** in `fingerprint.py`:
   - I/O sequence: Levenshtein (edit) distance, normalized to `[0.0, 1.0]`
   - Operation histogram: cosine similarity
   - CFG shape: Weisfeiler-Leman graph kernel or simple structural comparison (node/edge count ratio, loop count match)
   - Computation DAG: graph edit distance (approximate, since exact is NP-hard) or subgraph matching
   - Type signature: exact match (binary 0 or 1)

3. **Overall scoring function**:
   - Weighted combination of per-feature similarities
   - Default weights: I/O sequence (0.30), computation DAG (0.30), CFG shape (0.20), operation histogram (0.15), type signature (0.05)
   - Configurable via CLI flags

4. **Tests for Phase 2**
   - Pair of identical programs: score should be 1.0
   - Pair of clearly different programs: score should be low
   - Pair of semantically equivalent but syntactically different programs: score should be high

### Deliverables

- `src/semantic_equiv/fingerprint.py`
- `test/semantic_equiv/test_fingerprint.py`

### External Dependencies

- None beyond Phase 1

---

## Phase 3: Z3 Symbolic Encoding and Formal Verification

**Goal**: Encode LLVM IR programs as Z3 formulas and prove (or disprove) semantic equivalence for all inputs within bounds.

### Tasks

1. **LLVM IR to Z3 encoder** in `z3_encoder.py`:
   - **Instruction encoding**: Map each LLVM IR instruction to Z3 expressions:
     - `add/sub/mul/sdiv/srem` -> Z3 `BitVecVal` arithmetic (or `Int` for simplicity)
     - `icmp` -> Z3 boolean comparisons
     - `select` -> Z3 `If(cond, true_val, false_val)`
     - `phi` -> Z3 `If` based on which predecessor block was taken
     - `sext/zext/trunc` -> Z3 bit-vector operations
   - **I/O modeling**:
     - Each `cin` read: create a fresh Z3 symbolic variable (`Int` or `BitVec`)
     - Each `cout` write: record the Z3 expression being output
     - The program's semantics is captured as: `[output_expr_1, output_expr_2, ...]` as functions of `[input_var_1, input_var_2, ...]`
   - **Control flow encoding**:
     - Straight-line code: sequential constraint accumulation
     - Conditional branches: use Z3 `If` to merge values from both paths
     - Loops: unroll to bound K, converting loop body into K nested conditionals
   - **API**: `encoder = Z3Encoder(); encoder.encode(parsed_module); outputs = encoder.get_outputs()`

2. **Equivalence checker** in `z3_encoder.py`:
   - Takes two encoded programs
   - Verifies they have the same number and types of I/O operations
   - Constructs the query: `Exists(inputs): outputs_A != outputs_B`
   - Runs Z3 solver
   - Returns one of:
     - `EQUIVALENT` (UNSAT — no differing inputs exist)
     - `COUNTEREXAMPLE` (SAT — provides concrete inputs where outputs differ)
     - `UNKNOWN` (solver timeout or resource exhaustion)

3. **Loop unrolling**:
   - Detect back-edges in CFG (loops)
   - Unroll loop body K times (configurable, default K=10)
   - After unrolling, the program is a DAG (no cycles), suitable for direct Z3 encoding
   - Report if the bound was hit (equivalence proof is then valid only within bounds)

4. **Tests for Phase 3**
   - Two identical straight-line programs: Z3 says EQUIVALENT
   - Two programs that differ on one operation: Z3 provides counterexample
   - Program with if/else: verify Z3 handles conditional paths
   - Program with a simple loop: verify unrolling and bounded equivalence

### Deliverables

- `src/semantic_equiv/z3_encoder.py`
- `test/semantic_equiv/test_z3_encoder.py`

### External Dependencies

- `z3-solver` (Python package, installed via pip)

---

## Phase 4: CLI Driver and Reporting

**Goal**: Wire all tiers together into a usable command-line tool with clean output.

### Tasks

1. **`driver.py`** — CLI entry point:
   - Argument parsing:
     - Positional: `cpp1.cpp cpp2.cpp`
     - `--level {static,formal,all}` — which tiers to run (default: `all`)
     - `--loop-bound K` — loop unrolling bound for Z3 (default: 10)
     - `--clang PATH` — path to clang binary
     - `--opt PATH` — path to opt binary
     - `--verbose` — show intermediate IR and Z3 formulas
     - `--json` — output results as JSON (for CI integration)
   - Orchestration: run selected tiers in order, pass results to reporter
   - Error handling: missing clang/opt, compilation failures, Z3 timeouts

2. **`report.py`** — output formatting:
   - Terminal output with clear sections per tier
   - Final verdict line
   - JSON output mode for machine consumption
   - Verbose mode: print normalized IR, Z3 formula, solver stats
   - When a counterexample is found: show the concrete input values and the differing outputs from each program

3. **Entry point registration** in `pyproject.toml`:
   ```toml
   [project.scripts]
   cobol-translate = "cobol_translate:main"
   cobol-equiv = "semantic_equiv.driver:main"
   ```

4. **End-to-end tests**:
   - Full pipeline test: COBOL -> cobol-translate -> C++ -> cobol-equiv -> verdict
   - Test with equivalent programs, different programs, and edge cases

### Deliverables

- `src/semantic_equiv/driver.py`
- `src/semantic_equiv/report.py`
- `test/semantic_equiv/test_e2e.py`
- Updated `pyproject.toml`

### External Dependencies

- None beyond previous phases

---

## Phase 5 (Optional): Advanced Extensions

**Goal**: Handle edge cases and expand capability beyond basic COBOL programs.

### Tasks (pick as needed)

1. **KLEE integration** — For programs too complex for direct Z3 encoding:
   - Compile both C++ files to LLVM bitcode (`clang -emit-llvm -c`)
   - Generate a KLEE harness that links both programs and asserts output equivalence
   - Invoke KLEE, collect results
   - Fall back to KLEE when Z3 reports UNKNOWN/timeout

2. **Testable emission mode** in the translator:
   - Add `--emit emitc-testable` to `cobol-translate`
   - Generates C++ with explicit function parameters (inputs) and return values (outputs) instead of `cin`/`cout`
   - Simplifies equivalence checking: no I/O modeling needed, just pure function comparison

3. **Batch mode and regression testing**:
   - `cobol-equiv --batch manifest.json` where manifest lists pairs to compare
   - Produce a summary report (pass/fail counts, aggregate scores)
   - Integrate with CI: exit code 0 if all pairs equivalent, non-zero otherwise

4. **Delta reporting**:
   - When programs differ, identify which specific output expression diverges
   - Map the divergence back to source-level operations (using debug info in LLVM IR)
   - Show: "Output #2 differs: program A outputs `input_1 + 3`, program B outputs `input_1 + 2`"

5. **String and floating-point support**:
   - Extend Z3 encoding to handle string operations (Z3 has a string theory)
   - Handle floating-point comparisons with configurable epsilon tolerance

### Deliverables

- Depends on which extensions are selected
- Each extension is self-contained and can be implemented independently

---

## Summary

| Phase | Builds | Key Output | Depends On |
|-------|--------|-----------|------------|
| 1 | Normalization + IR Parsing | `normalize.py`, `ir_parser.py` | clang, opt |
| 2 | Static Fingerprinting | `fingerprint.py` + similarity scores | Phase 1 |
| 3 | Z3 Verification | `z3_encoder.py` + equivalence proofs | Phase 1, z3-solver |
| 4 | CLI + Reporting | `driver.py`, `report.py` + usable tool | Phase 1-3 |
| 5 | Extensions | KLEE, batch mode, testable emit, delta reports | Phase 4 |

Phases 2 and 3 are independent of each other and can be developed in parallel after Phase 1 is complete.
