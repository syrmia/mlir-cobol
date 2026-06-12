       IDENTIFICATION DIVISION.
       PROGRAM-ID. BXX-NNN-PIC-TEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  C         PIC NNN VALUE "first".
       01  L         PIC NNN Value "second".
       PROCEDURE DIVISION.
           DISPLAY C.
           DISPLAY L.
           STOP RUN.