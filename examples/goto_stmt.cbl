       IDENTIFICATION DIVISION.
       PROGRAM-ID. GOTOSTMT.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           77 WS-VAR PIC 99 VALUE 10.
       PROCEDURE DIVISION.
       PARA-1.
           DISPLAY 'IN PARA-1'.
           GO TO PARA-3.
       PARA-2.
           DISPLAY 'IN PARA-2'.
           STOP RUN.
       PARA-3.
           DISPLAY 'IN PARA-3'.
           STOP RUN.
