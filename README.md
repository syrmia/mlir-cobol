# MLIR Dialect for COBOL

An MLIR Dialect for COBOL

## Example

```
$ ./cobol-front.py  test.cbl 
Warning: couldn’t parse statement: ELSE
Warning: couldn’t parse statement: END-IF
builtin.module {
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
}
```
