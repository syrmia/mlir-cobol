       IDENTIFICATION DIVISION.
       PROGRAM-ID. IFNOELSE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           77 NUM-A PIC 99.
       PROCEDURE DIVISION.
           MOVE 10 TO NUM-A.
           IF (NUM-A > 5)
               DISPLAY 'GREATER THAN FIVE'
           END-IF
           STOP RUN.
