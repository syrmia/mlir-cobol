       IDENTIFICATION DIVISION.
       PROGRAM-ID. BXX-NNN-PIC-TEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  C         PIC BXX VALUE " dd".
       01  L         PIC BXX Value " bbbbbbb".
       PROCEDURE DIVISION.
           DISPLAY C.
           DISPLAY L.
           STOP RUN.