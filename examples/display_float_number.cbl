       IDENTIFICATION DIVISION.
       PROGRAM-ID. display.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-NAME PIC A(20) VALUE 'Duke'.
       01 WS-AGE  PIC 9(2) VALUE 32.
       01 WS-WEIGHT  PIC 9V9 VALUE 32.4.
       PROCEDURE DIVISION.
       Main-Process.
           DISPLAY 'Name: ' WS-NAME.
           DISPLAY 'Age: ' WS-AGE.
           DISPLAY 'WEIGHT: ' WS-WEIGHT.
           STOP RUN.
