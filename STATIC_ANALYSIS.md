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
Structural comparison inspects code similarity based on program structure ranging from modules and functions, down to blocks and instructions. It detects similarities even when code is not semantically identical but produces the same result, such as commutative operations or swapped comparison predicates (e.g. a < b is equivalent to b >= a).

## Z3 Formal Verification
Z3, or Z3 theorem prover, is a Satisfiability Modulo Theories (SMT) solver developed by Microsoft. Unlike heuristic-based approaches, Z3 performs formal verification of program equivalence by relying on mathematical reasoning rather than approximations.

It works by checking whether there exists an input that causes the two programs to behave differently.
In this project, LLVM IR operations are translated into symbolic formulas, where program variables are modeled as a symbolic variables and program operations are modeled as logical functions. Input and output operations (such as cin and cout) are abstracted as symbolic input and output events. Loops are handled via bounded unrolling. Program equivalence is reduced to a satisfiability problem that checks whether there exists any input for which the two programs produce different outputs.
If such input exists, Z3 returns a concrete counterexample. Otherwise, the programs are considered equivalent within the given bounds.

### Example:
Given the following C++ code:
```cpp
int add(int a, int b)
{
    return a + b;
}
```
and a reference implementation:
```cpp
int add(int a, int b)
{
    return b + a;
}
```
Both functions compile to equivalent LLVM IR, differing only in operands order. After compiling to LLVM IR, both functions contain an addition instruction with swapped operands:
```llvm
%r = add i32 %a, %b
ret i32 %r
```
The LLVM IR is symbolically encoded using the Z3 Python API, where program variables are represented as symbolic integers:
```py
z3.Int("%a") + z3.Int("%b")
```
To check equivalence, the analysis constructs a SMT query that asks whether there exists any input for which the two implementations produce different results:
```
(declare-fun a () Int)
(declare-fun b () Int)
(assert (not (= (+ a b) (+ b a))))
(check-sat)
```
Since the formula is unsatisfiable, no such input exists, and the two functions are proven to be semantically equivalent.
