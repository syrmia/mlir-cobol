       IDENTIFICATION DIVISION.
       PROGRAM-ID. DISPLAYMIX.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-NAME PIC A(10) VALUE 'Alice'.
       01 WS-AGE  PIC 9(3) VALUE 30.
       PROCEDURE DIVISION.
       Main-Process.
           DISPLAY 'Name: ' WS-NAME ' Age: ' WS-AGE.
           STOP RUN.
