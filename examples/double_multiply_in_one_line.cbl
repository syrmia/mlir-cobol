       IDENTIFICATION DIVISION.
       PROGRAM-ID. display.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 X  PIC 9(2) VALUE 5.
       01 Y  PIC 9(2) VALUE 2.
       01 Z PIC 9(2) VALUE 3.
       PROCEDURE DIVISION.
       Main-Process.
           MULTIPLY X BY Y Z.
           DISPLAY "X=" X " Y=" Y " Z=" Z.
           STOP RUN.
