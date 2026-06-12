       IDENTIFICATION DIVISION.
       PROGRAM-ID. display.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 X  PIC 9(2) VALUE 32.
       01 Y  PIC 9V9999 VALUE 32.4.
       PROCEDURE DIVISION.
       Main-Process.
           DISPLAY 'X: ' X.
           DISPLAY 'Y: ' Y.
           ADD X TO Y.
           STOP RUN.
