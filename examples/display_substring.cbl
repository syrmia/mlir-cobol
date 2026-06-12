IDENTIFICATION   DIVISION.
       PROGRAM-ID.      prog.
       DATA             DIVISION.
       WORKING-STORAGE  SECTION.
       01 X             PIC X(4) VALUE "abcd".
       
       PROCEDURE        DIVISION.
           DISPLAY X(1:3).
           STOP RUN.