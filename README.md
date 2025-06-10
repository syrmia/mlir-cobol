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

2. Install Python dependencies:
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
- `cobol.stop` - Program termination (STOP RUN)

## Example

Input COBOL program (`test.cbl`):
```cobol
 IDENTIFICATION DIVISION.
 PROGRAM-ID. TEST1.

 DATA DIVISION.
 WORKING-STORAGE SECTION.
 01  WS-MESSAGE   PIC X(20) VALUE "Hello World".
 01  WS-NUMBER    PIC 9(3)  VALUE 42.

 PROCEDURE DIVISION.
 MAIN-PARAGRAPH.
     DISPLAY WS-MESSAGE " – value is " WS-NUMBER
     STOP RUN.
```

Generated MLIR output:
```mlir
builtin.module {
  "cobol.func"() ({
    %0 = "cobol.declare"() {sym_name = "WS-MESSAGE"} : () -> !cobol.string<20 : i32>
    %1 = "cobol.constant"() {value = "Hello World"} : () -> !cobol.string<20 : i32>
    "cobol.move"(%1, %0) : (!cobol.string<20 : i32>, !cobol.string<20 : i32>) -> ()
    %2 = "cobol.declare"() {sym_name = "WS-NUMBER"} : () -> !cobol.decimal<3 : i32, 0 : i32>
    %3 = "cobol.constant"() {value = 42 : i32} : () -> !cobol.decimal<3 : i32, 0 : i32>
    "cobol.move"(%3, %2) : (!cobol.decimal<3 : i32, 0 : i32>, !cobol.decimal<3 : i32, 0 : i32>) -> ()
    %4 = "cobol.constant"() {value = " \u2013 value is "} : () -> !cobol.string<12 : i32>
    "cobol.display"(%0, %4, %2) : (!cobol.string<20 : i32>, !cobol.string<12 : i32>, !cobol.decimal<3 : i32, 0 : i32>) -> ()
    "cobol.stop"() : () -> ()
  }) {sym_name = "TEST1", function_type = () -> ()} : () -> ()
}
```

## Build GCC with COBOL support

```bash
$ git clone https://github.com/gcc-mirror/gcc.git
$ cd gcc && mkdir build && cd build && ../configure --enable-languages=cobol && make -j3
```

## TODOs

1. Move to gcobol: https://gcc.gnu.org/onlinedocs/gcobol/gcobol.html
  - just frontend
  - seems it is more robust than `koopa`
  - try to serialize the AST parsed and populate that into MLIR

## License

This project is licensed under the terms specified in the LICENSE file.
