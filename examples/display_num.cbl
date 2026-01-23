       IDENTIFICATION DIVISION.
       PROGRAM-ID. SimpleVariable.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-AGE PIC 9(3) VALUE 25.
       01 WS-NAME PIC X(4) VALUE "Duke".
       PROCEDURE DIVISION.
       Main-Process.
           DISPLAY WS-AGE.
           DISPLAY WS-NAME.
           STOP RUN.
