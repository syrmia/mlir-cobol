IDENTIFICATION   DIVISION.
       PROGRAM-ID.      prog.
       DATA             DIVISION.
       WORKING-STORAGE  SECTION.
  
       01 Z             PIC 9 value 5.
       01 X1             PIC 9.
       01 X12            PIC 9 external.
       01 X             PIC 9V9 external.
       PROCEDURE        DIVISION.
            DISPLAY Z.
           STOP RUN.