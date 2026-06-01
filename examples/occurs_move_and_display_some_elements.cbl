       IDENTIFICATION   DIVISION.
       PROGRAM-ID.      prog.
       DATA             DIVISION.
       WORKING-STORAGE  SECTION.

       01 X PIC 9 OCCURS 10.

       PROCEDURE        DIVISION.
           MOVE 1 TO X(1).
           MOVE 5 TO X(2). 
           DISPLAY X(1).
           DISPLAY X(2).
           STOP RUN.
