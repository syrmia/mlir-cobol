# MLIR Dialect for COBOL

An MLIR Dialect for COBOL

## Example

```
$ ./cobol-front.py  test.cbl 
WORKING-STORAGE FIELDS:
  • NUM1: level=1, PIC=9(3), VALUE=7.
  • NUM2: level=1, PIC=9(3), VALUE=4.
  • TOTAL: level=1, PIC=9(4), VALUE=0.
  • STATUS: level=1, PIC=X(10), VALUE=SPACES.

PROCEDURE DIVISION STATEMENTS:
  - MOVE NUM1 TO TOTAL
  - ADD  NUM2 TO TOTAL
  - IF TOTAL > 10
  - MOVE "TOO LARGE" TO STATUS
  - ELSE
  - MOVE "OK" TO STATUS
  - END-IF
  - STOP RUN.
```
