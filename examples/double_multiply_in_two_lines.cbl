       IDENTIFICATION DIVISION.
       PROGRAM-ID. display.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 X  PIC 9(2) VALUE 32.
       01 Y  PIC 9(2) VALUE 236.
       01 Z PIC 9(2) VALUE 22.
       PROCEDURE DIVISION.
       Main-Process.
           MULTIPLY X BY Y.
           MULTIPLY Y BY Z.
           STOP RUN.
