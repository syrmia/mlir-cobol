# MLIR-COBOL: MLIR Dialect for COBOL (POC)

An experimental MLIR dialect for COBOL built using xDSL.

## Overview

This project implements:
- A custom COBOL dialect for MLIR with operations modeling COBOL semantics
- A frontend compiler (`cobol-front.py`) that parses COBOL source files and generates MLIR
- ...

## Project Structure

```
mlir-cobol/
├── src/
│   ├── cobol_dialect.py    # COBOL dialect definition
│   └── cobol-front.py       # COBOL to MLIR frontend
├── test.cbl                 # Example COBOL program
└── README.md
```

## Installation

1. Create and activate a Python virtual environment:
```bash
python3 -m venv venv
source venv/bin/activate
```

2. Install dependencies:
```bash
pip install xdsl
```

## Usage

To compile a COBOL program to MLIR:

```bash
cd src/
python cobol-front.py ../test.cbl
```

## COBOL Dialect Operations

The dialect includes the following operations:

### Types
- `!cobol.string<length>` - Fixed-length string type
- `!cobol.decimal<digits, scale>` - Decimal type with precision

### Operations
- `cobol.func` - Represents a COBOL program with its PROCEDURE DIVISION
- `cobol.declare` - Variable declaration
- `cobol.constant` - Literal values
- `cobol.move` - Data movement (COBOL MOVE statement)
- `cobol.add` - Arithmetic addition
- `cobol.compare` - Comparison operations (EQ, LT, GT)
- `cobol.if` - Conditional execution with then/else regions
- `cobol.stop` - Program termination (STOP RUN)

## Example

Input COBOL program (`test.cbl`):
```cobol
IDENTIFICATION DIVISION.
PROGRAM-ID. SumCheck.

DATA DIVISION.
WORKING-STORAGE SECTION.
01  NUM1    PIC 9(3)    VALUE  7.
01  NUM2    PIC 9(3)    VALUE  4.
01  TOTAL   PIC 9(4)    VALUE  0.
01  STATUS  PIC X(10)   VALUE  SPACES.

PROCEDURE DIVISION.
    MOVE NUM1 TO TOTAL
    ADD  NUM2 TO TOTAL

    IF TOTAL > 10
        MOVE "TOO LARGE" TO STATUS
    ELSE
        MOVE "OK" TO STATUS
    END-IF

    STOP RUN.
```

Generated MLIR output:
```mlir
builtin.module {
  "cobol.func"() ({
    %0 = "cobol.declare"() {sym_name = "NUM1"} : () -> !cobol.decimal<3 : i32, 0 : i32>
    %1 = "cobol.constant"() {value = 7 : i32} : () -> !cobol.decimal<3 : i32, 0 : i32>
    "cobol.move"(%1, %0) : (!cobol.decimal<3 : i32, 0 : i32>, !cobol.decimal<3 : i32, 0 : i32>) -> ()
    %2 = "cobol.declare"() {sym_name = "NUM2"} : () -> !cobol.decimal<3 : i32, 0 : i32>
    %3 = "cobol.constant"() {value = 4 : i32} : () -> !cobol.decimal<3 : i32, 0 : i32>
    "cobol.move"(%3, %2) : (!cobol.decimal<3 : i32, 0 : i32>, !cobol.decimal<3 : i32, 0 : i32>) -> ()
    %4 = "cobol.declare"() {sym_name = "TOTAL"} : () -> !cobol.decimal<4 : i32, 0 : i32>
    %5 = "cobol.constant"() {value = 0 : i32} : () -> !cobol.decimal<4 : i32, 0 : i32>
    "cobol.move"(%5, %4) : (!cobol.decimal<4 : i32, 0 : i32>, !cobol.decimal<4 : i32, 0 : i32>) -> ()
    %6 = "cobol.declare"() {sym_name = "STATUS"} : () -> !cobol.string<10 : i32>
    %7 = "cobol.constant"() {value = "SPACES"} : () -> !cobol.string<10 : i32>
    "cobol.move"(%7, %6) : (!cobol.string<10 : i32>, !cobol.string<10 : i32>) -> ()
    "cobol.move"(%0, %4) : (!cobol.decimal<3 : i32, 0 : i32>, !cobol.decimal<4 : i32, 0 : i32>) -> ()
    %8 = "cobol.add"(%2, %4) : (!cobol.decimal<3 : i32, 0 : i32>, !cobol.decimal<4 : i32, 0 : i32>) -> !cobol.string<10 : i32>
    %9 = "cobol.constant"() {value = 10 : i32} : () -> i32
    %10 = "cobol.compare"(%8, %9) {cond = "GT"} : (!cobol.string<10 : i32>, i32) -> i1
    "cobol.if"(%10) ({
    ^0:
    }, {
    ^1:
    }) : (i1) -> ()
    %11 = "cobol.constant"() {value = "TOO LARGE"} : () -> !cobol.string<10 : i32>
    "cobol.move"(%11, %6) : (!cobol.string<10 : i32>, !cobol.string<10 : i32>) -> ()
    %12 = "cobol.constant"() {value = "OK"} : () -> !cobol.string<10 : i32>
    "cobol.move"(%12, %6) : (!cobol.string<10 : i32>, !cobol.string<10 : i32>) -> ()
    "cobol.stop"() : () -> ()
  }) {sym_name = "SumCheck", function_type = () -> ()} : () -> ()
}
```

## License

This project is licensed under the terms specified in the LICENSE file.
