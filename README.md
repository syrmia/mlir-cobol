# MLIR-COBOL: MLIR Dialect for COBOL (POC)

An experimental MLIR dialect for COBOL built using xDSL, and more.

## Overview

This project implements:
- A custom COBOL dialect for MLIR with operations modeling COBOL semantics
- A frontend compiler that parses COBOL source files and generates MLIR
- ...

## Project Structure

```
mlir-cobol/
├── src/
│   ├── cobol_dialect.py      # COBOL dialect definition
│   ├── cobol_translate.py    # Main driver tool
│   ├── cobol_front.py        # COBOL to MLIR frontend
│   ├── emitc_lowering.py     # EmitC lowering (TBD)
│   └── util/
│       ├── lowering.py       # Partial lowering from cobol dialect to xdsl dialects
│       └── xml_handlers.py   # XML file readers
├── examples/                 # Example COBOL programs
├── test/                     # Lit tests
└── README.md
```

## Installation

1. Create and activate a Python virtual environment:
```bash
python3 -m venv venv
source venv/bin/activate
```

2. Install the package with dependencies:
```bash
pip install -e .
```

3. Download the KOOPA COBOL parser:
```bash
wget https://github.com/krisds/koopa/releases/download/v20250222/koopa-20250222.jar -O koopa.jar
export KOOPA_PATH=$PWD
```

## Usage

After installation, `cobol-translate` is available:

```bash
cobol-translate examples/hello.cbl                    # Output COBOL MLIR dialect
cobol-translate examples/ifelse.cbl --emit cobol-mlir # Same as above
cobol-translate examples/ifelse.cbl --emit emitc      # Output EmitC dialect (TBD)
cobol-translate examples/ifelse.cbl --emit llvm-mlir  # Output LLVM dialect (TBD)
cobol-translate examples/hello.cbl -o output.mlir     # Write to file
cobol-translate --help                                # Show all options
```

## Running Tests

Install dev dependencies and run the lit tests:

```bash
pip install -e ".[dev]"
lit test/
```

NOTE: Before running the tests, double check you installed `lit` and `FileCheck` as:

```bash
pip install lit

sudo apt install llvm-18-tools
sudo ln -s /usr/bin/FileCheck-18 /usr/bin/FileCheck
```

## COBOL Dialect Operations

The dialect includes the following operations:

### Types
- `!cobol.string<length>` - Fixed-length string type
- `!cobol.decimal<digits, scale>` - Decimal type with precision

### Operations
- `cobol.accept` - Input (COBOL ACCEPT statement)
- `cobol.constant` - Literal values
- `cobol.declare` - Variable declaration
- `cobol.display` - Output (COBOL DISPLAY statement)
- `cobol.func` - Represents a COBOL program with its PROCEDURE DIVISION
- `cobol.is` - Is operator (COBOL IS operator, also IS NOT)
- `cobol.move` - Data movement (COBOL MOVE statement)
- `cobol.not` - Unary not operator
- `cobol.set` - COBOL SET operator
- `cobol.stop` - Program termination (STOP RUN)
- ...

## Example

Input COBOL program (`examples/ifelse.cbl`):
```cobol
IDENTIFICATION DIVISION.
PROGRAM-ID. HELLOWORD.
ENVIRONMENT DIVISION.
DATA DIVISION.
WORKING-STORAGE SECTION.
    77 OPERAND1 PIC 99.
    77 OPERAND2 PIC 99.
PROCEDURE DIVISION.
    MOVE 10 TO OPERAND1.
    MOVE 8 TO OPERAND2.
    IF OPERAND2 is numeric and (OPERAND1 > OPERAND2)
        DISPLAY 'OPERAND2 is smaller than OPERAND1'
    ELSE
        DISPLAY 'OPERAND2 is not smaller or numeric'
    END-IF
    STOP RUN.
```

Generated MLIR output:
```mlir
builtin.module {
  "cobol.func"() ({
    %0 = "cobol.declare"() {sym_name = "OPERAND1"} : () -> !cobol.string<0 : i32>
    %1 = "cobol.declare"() {sym_name = "OPERAND2"} : () -> !cobol.string<0 : i32>
    %2 = "cobol.constant"() {value = "10"} : () -> !cobol.string<2 : i32>
    "cobol.move"(%2, %0) : (!cobol.string<2 : i32>, !cobol.string<0 : i32>) -> ()
    %3 = "cobol.constant"() {value = "8"} : () -> !cobol.string<1 : i32>
    "cobol.move"(%3, %1) : (!cobol.string<1 : i32>, !cobol.string<0 : i32>) -> ()
    %4 = "cobol.is"(%1) <{kind = "numeric", is_positive = "true"}> : (!cobol.string<0 : i32>) -> !cobol.decimal<1 : i32, 1 : i32>
    %5 = arith.cmpi sgt, %0, %1 : !cobol.string<0 : i32>
    %6 = arith.andi %4, %5 : !cobol.decimal<1 : i32, 1 : i32>
    scf.if %6 {
      %7 = "cobol.constant"() {value = "OPERAND2 is smaller than OPERAND1"} : () -> !cobol.string<33 : i32>
      "cobol.display"(%7) : (!cobol.string<33 : i32>) -> ()
    } else {
      %8 = "cobol.constant"() {value = "OPERAND2 is not smaller or numeric"} : () -> !cobol.string<34 : i32>
      "cobol.display"(%8) : (!cobol.string<34 : i32>) -> ()
    }
    "cobol.stop"() : () -> ()
  }) {sym_name = "HELLOWORD", function_type = () -> ()} : () -> ()
}
```

## Run tests

```bash
(venv) $ lit test  
-- Testing: 5 tests, 5 workers --
PASS: mlir-cobol :: hello.test (1 of 5)
PASS: mlir-cobol :: just_stop.test (2 of 5)
PASS: mlir-cobol :: simple_input.test (3 of 5)
PASS: mlir-cobol :: decls.test (4 of 5)
PASS: mlir-cobol :: ifelse.test (5 of 5)

Testing Time: 0.64s

Total Discovered Tests: 5
  Passed: 5 (100.00%)

```

## License

This project is licensed under the terms specified in the LICENSE file.
