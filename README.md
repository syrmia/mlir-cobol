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
│   ├── cobol_dialect.py      # COBOL dialect definition
│   ├── cobol-front.py        # COBOL to MLIR frontend
│   └── util/
│       ├── lowering.py       # Partial lowering from cobol dialect to xdsl dialects
│       └── xml_handlers.py   # XML file readers
├── test/                     # Example COBOL programs
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
python src/cobol\_front.py test/ifelse.cbl
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

## Example

Input COBOL program (`ifelse.cbl`):
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
