# Semantic Equivalence Analysis — Design Document

## 1. Motivation

The mlir-cobol project translates COBOL source code to C++ through an MLIR-based pipeline:

```
COBOL --> KOOPA (XML) --> COBOL Dialect MLIR --> EmitC --> C++
```

The final stage of this pipeline needs a tool that can answer: **"Does the generated C++ behave the same as a reference C++ implementation?"** This is the semantic equivalence problem.

### Why Not CBMC?

CBMC operates on C/C++ source directly and cannot handle many C++ features (constexpr, templates, STL containers, etc.). The generated C++ uses `std::string`, `std::cout`, `std::cin`, and standard integer types — features that cause CBMC to choke or produce incomplete results.

### Why Not Pure Static Analysis?

Clang AST-level comparison is syntactic, not semantic. Two programs can look completely different at the AST level but compute identical results. Static analysis alone gives similarity scores but never proofs.

## 2. Core Insight: Work at LLVM IR

Both C++ programs compile cleanly to LLVM IR via Clang. At the LLVM IR level:

- All C++ feature complexity is resolved by the Clang frontend
- The representation is typed, structured, and well-tooled
- Normalization passes eliminate superficial differences
- Z3 and KLEE both operate natively on LLVM IR / bitcode

```
cpp1.cpp --> clang -S -emit-llvm --> prog1.ll --> opt (normalize) --> prog1_canon.ll
                                                                           |
                                                                     [ COMPARE ]
                                                                           |
cpp2.cpp --> clang -S -emit-llvm --> prog2.ll --> opt (normalize) --> prog2_canon.ll
```

## 3. Architecture Overview

The tool — `cobol-equiv` — uses a three-tier analysis. Each tier trades speed for confidence. Tiers compose: you can stop after Tier 1 for quick screening, or run all three for maximum assurance.

```
+---------------------------------------------------------------+
|                cobol-equiv: Semantic Equivalence Tool          |
+---------------------------------------------------------------+
|                                                               |
|  Tier 1: STATIC SEMANTIC FINGERPRINTING (fast, approximate)  |
|  |-- Extract features from normalized LLVM IR                |
|  |-- Compare via graph matching / similarity metrics          |
|  +-- Output: similarity score [0.0, 1.0]                     |
|                                                               |
|  Tier 2: DIFFERENTIAL TESTING (medium confidence)             |
|  |-- Z3 symbolic encoding of both programs                   |
|  |-- Generate diverse test inputs automatically               |
|  |-- Cross-validate outputs                                   |
|  +-- Output: test results + any counterexamples               |
|                                                               |
|  Tier 3: BOUNDED FORMAL VERIFICATION (highest confidence)     |
|  |-- Full Z3 encoding with loop unrolling to bound K          |
|  |-- Prove: for-all inputs, outputs match                     |
|  +-- Output: EQUIVALENT / COUNTEREXAMPLE / UNKNOWN            |
|                                                               |
+---------------------------------------------------------------+
```

## 4. Tier 1: Static Semantic Fingerprinting

### Purpose

Fast screening. Produces a similarity score. If the score is low, the programs are clearly different and there is no need to run expensive verification. If high, proceed to Tier 2/3 for confirmation.

### Normalization

Both C++ files are compiled to LLVM IR and then normalized using `opt`:

```
opt -passes='mem2reg,instcombine,simplifycfg,dce,reassociate' prog.ll -o prog_norm.ll
```

This eliminates superficial differences:
- Different variable names (SSA renumbering)
- Dead code
- Different instruction ordering for the same computation
- Different but equivalent arithmetic expressions

### Feature Extraction

From the normalized LLVM IR, extract these semantic features per function:

| Feature | What It Captures | Comparison Method |
|---------|-----------------|-------------------|
| I/O operation sequence | Order and types of `cin`/`cout` calls | Sequence alignment (Levenshtein distance) |
| Computation DAG | Dataflow from inputs through arithmetic to outputs | Graph edit distance |
| CFG shape | Branch structure, loop nesting, basic block count | Graph isomorphism (Weisfeiler-Leman) |
| Operation histogram | Counts of add/mul/cmp/br/call instructions | Cosine similarity |
| Type signature | Parameter types, return type, local variable types | Exact match |

### Scoring

The overall similarity score is a weighted combination:

```
score = w1 * io_sim + w2 * computation_sim + w3 * cfg_sim + w4 * op_sim + w5 * type_sim
```

Default weights emphasize I/O patterns and computation structure, since those capture observable behavior most directly.

### Strengths and Limitations

**Catches**: Renamed variables, reordered independent statements, algebraically equivalent expressions (after `instcombine`), cosmetic differences.

**Misses**: Algorithmically different implementations that produce identical results (e.g., two sorting algorithms). These require Tier 2/3.

## 5. Tier 2/3: Z3-Based Verification

### Why Z3 Over KLEE

For the relatively simple programs generated from COBOL (no heap allocation, no recursion, bounded loops), Z3 is the better choice:

- Pure Python integration (`pip install z3-solver`)
- No heavy LLVM-version-specific KLEE installation
- Gives actual proofs (not just test coverage)
- Handles the arithmetic and control flow in COBOL programs cleanly

KLEE remains an option for future expansion if programs become too complex for direct Z3 encoding.

### I/O Model

COBOL programs have a clean I/O model:
- **Inputs**: `ACCEPT` statements (mapped to `std::cin >> var`)
- **Outputs**: `DISPLAY` statements (mapped to `std::cout << expr`)

For equivalence checking, model these as:
- Each `cin` read becomes a fresh Z3 symbolic variable
- Each `cout` write becomes a Z3 expression over the symbolic inputs
- Two programs are equivalent iff their output expression sequences are identical for all input assignments

### LLVM IR to Z3 Encoding

Each LLVM IR instruction maps to a Z3 constraint:

```python
from z3 import *

class LLVMToZ3:
    def __init__(self):
        self.vars = {}       # SSA name -> Z3 expression
        self.inputs = []     # symbolic input variables
        self.outputs = []    # output expressions

    def encode_instruction(self, inst):
        match inst.opcode:
            case "add":
                self.vars[inst.result] = self.vars[inst.op1] + self.vars[inst.op2]
            case "sub":
                self.vars[inst.result] = self.vars[inst.op1] - self.vars[inst.op2]
            case "mul":
                self.vars[inst.result] = self.vars[inst.op1] * self.vars[inst.op2]
            case "icmp":
                lhs, rhs = self.vars[inst.op1], self.vars[inst.op2]
                pred_map = {
                    "eq": lambda a, b: a == b,
                    "ne": lambda a, b: a != b,
                    "sgt": lambda a, b: a > b,
                    "slt": lambda a, b: a < b,
                    "sge": lambda a, b: a >= b,
                    "sle": lambda a, b: a <= b,
                }
                self.vars[inst.result] = pred_map[inst.predicate](lhs, rhs)
            case "select":
                cond = self.vars[inst.cond]
                self.vars[inst.result] = If(cond, self.vars[inst.true_val],
                                                  self.vars[inst.false_val])
            case "call":
                if is_output_call(inst):
                    self.outputs.append(self.vars[inst.args[0]])
                elif is_input_call(inst):
                    sym = Int(f"input_{len(self.inputs)}")
                    self.vars[inst.result] = sym
                    self.inputs.append(sym)
```

### Equivalence Query

```python
def check_equivalence(encoder_a, encoder_b):
    s = Solver()

    # Programs must have same number of outputs
    if len(encoder_a.outputs) != len(encoder_b.outputs):
        return "DIFFERENT (output count mismatch)"

    # Assert that at least one output differs
    diff = Or(*[a != b for a, b in zip(encoder_a.outputs, encoder_b.outputs)])
    s.add(diff)

    result = s.check()
    if result == unsat:
        return "EQUIVALENT (proven for all inputs)"
    elif result == sat:
        model = s.model()
        return f"COUNTEREXAMPLE: {model}"
    else:
        return "UNKNOWN (solver timeout)"
```

### Loop Handling

For programs with loops, unroll to a configurable bound K:

```
--loop-bound 20   (default: 10)
```

The unrolled loop becomes straight-line code with nested `If-Then-Else`, which Z3 handles natively. The equivalence proof is valid within the unrolling bound.

### Conditional Branch Handling

LLVM IR conditional branches (`br i1 %cond, label %then, label %else`) are encoded as Z3 `If` expressions. This avoids path explosion — Z3 reasons about all paths simultaneously through its internal SAT/SMT solving.

## 6. Integration With Existing Pipeline

### End-to-End Usage

```
COBOL source --> cobol-translate --> generated.cpp
                                          |
                                    cobol-equiv  <-- reference.cpp
                                          |
                                   Equivalence Report
```

### CLI Interface

```bash
# Full analysis (all tiers)
cobol-equiv generated.cpp reference.cpp

# Static fingerprinting only (fast screening)
cobol-equiv generated.cpp reference.cpp --level static

# Formal verification only
cobol-equiv generated.cpp reference.cpp --level formal --loop-bound 20

# Pipeline integration
cobol-translate input.cbl --emit cpp -o generated.cpp
cobol-equiv generated.cpp reference.cpp
```

### Sample Output

```
=== Semantic Equivalence Analysis ===

Tier 1: Static Fingerprinting
  I/O pattern similarity:    1.00
  Computation similarity:    0.92
  Control flow similarity:   1.00
  Operation mix similarity:  0.95
  -----------------------------------
  Overall score:             0.97

Tier 2: Z3 Bounded Verification (loop bound K=10)
  Input variables:    2 (i32, i32)
  Output expressions: 3
  SMT constraints:    87
  Solver result:      UNSAT
  -----------------------------------
  Verdict:            EQUIVALENT (bounded)

=== RESULT: EQUIVALENT ===
```

## 7. Project Structure

New files added under `src/semantic_equiv/`:

```
src/
|-- cobol_dialect.py            # existing
|-- cobol_front.py              # existing
|-- cobol_translate.py          # existing
|-- emitc_lowering.py           # existing
|-- semantic_equiv/
|   |-- __init__.py
|   |-- driver.py               # CLI entry point
|   |-- normalize.py            # LLVM IR normalization (calls clang + opt)
|   |-- fingerprint.py          # Tier 1: feature extraction and comparison
|   |-- ir_parser.py            # LLVM IR text parser -> Python data structures
|   |-- z3_encoder.py           # Tier 2/3: LLVM IR -> Z3 formula encoding
|   +-- report.py               # Output formatting and reporting
+-- util/
    +-- xml_handlers.py         # existing
```

### Module Responsibilities

| Module | Purpose |
|--------|---------|
| `driver.py` | CLI argument parsing, orchestrates the three tiers, handles errors |
| `normalize.py` | Invokes `clang` and `opt` as subprocesses, manages temporary files |
| `ir_parser.py` | Parses LLVM IR text into Python dataclasses (Module, Function, BasicBlock, Instruction) |
| `fingerprint.py` | Extracts semantic features from parsed IR, computes similarity scores |
| `z3_encoder.py` | Walks parsed IR and builds Z3 formulas, runs equivalence queries |
| `report.py` | Formats analysis results for terminal output |

### New Dependencies

```toml
# In pyproject.toml
dependencies = [
    "xdsl @ git+https://github.com/syrmia/xdsl.git",
    "z3-solver",
]
```

### New Entry Point

```toml
# In pyproject.toml [project.scripts]
cobol-equiv = "semantic_equiv.driver:main"
```

## 8. Comparison With Alternatives

| Approach | Problem | Our Answer |
|----------|---------|------------|
| CBMC on C++ | Cannot handle constexpr, templates, STL | Compile to LLVM IR first; Clang handles all C++ |
| Clang AST comparison | Syntactic, not semantic | Normalize at IR level, then reason about semantics |
| Pure KLEE | Heavy dependency, hard to install, LLVM version coupling | Z3 is `pip install z3-solver`, pure Python |
| Pure static analysis | No proofs, only similarity scores | Z3 gives actual proofs for bounded programs |
| Manual test cases | Low coverage, labor-intensive | Z3 explores all inputs within bounds automatically |

## 9. Future Extensions

- **KLEE integration**: For programs with unbounded loops, deep recursion, or complex heap usage that exceed Z3's direct encoding capability.
- **Testable emission mode**: A `--emit emitc-testable` flag in `cobol-translate` that generates C++ with explicit function parameters instead of `cin`/`cout`, making equivalence checking simpler.
- **Batch mode**: Compare multiple COBOL/C++ pairs in a single run for regression testing.
- **Delta reporting**: When programs differ, report exactly which output expression diverges and under what input conditions.
