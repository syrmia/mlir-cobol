# Static analysis
The project provides automated options for performing static analysis on the generated C++ code:
- Static Fingerprinting (fingerprint.py)
- Structural Comparison (compare.py)
- Z3 Formal Verification (z3_encoder.py)

## Static fingerprinting
Static fingerprinting is a static analysis technique that extracts semantic characteristics from a program and compares them with those of a reference program. The comparison result is expressed as a similarity score in the range [0.0, 1.0], where higher values indicate greater similarity.
The following 5 traits are analyzed:
- I/O operation sequence - order and structure of input/output operations
- Computation DAG - use of SSA values
- CFG shape - the 'shape' of a program, that shows its structure and flow
- Operation histogram - frequency and distribution of operations
- Type signature - parameter and return types

## Structural comparison
Structural comparison inspects code similarity based on program structure ranging from modules and functions, down to blocks and instructions operations. It detects similarities even when code is not semantically identical but produces the same result, such as commutative operations or swapped comparison predicates (e.g. a < b is equivalent b >= a).

## Z3 Formal Verification
Encodes LLVM IR functions into Z3 symbolic formulas, models cin/cout as symbolic I/O, unrolls loops to a configurable bound, and asks Z3 to prove equivalence for all inputs or produce a concrete counterexample.

# Z3

Z3, or Z3 theorem prover, is a Satisfiability Modulo Theories (SMT) solver developed by Microsoft. Unlike heuristic-based approaches, Z3 performs formal verification of program equivalence by relying on mathematical reasoning rather than approximations.

It works by checking whether there exists an input that causes the two programs to behave differently.
LLVM IR operations are translated into symbolic formulas, where program variables are modeled as a symbolic variables and program operations are modeled as logical functions. Program equivalence is then reduced to a SMT satisfiability problem: the solver determines whether there exists any input that causes the programs to produce different outputs.
If such input exists, Z3 returns a concrete counterexample. Otherwise, the programs are considered equivalent within the given bounds.


