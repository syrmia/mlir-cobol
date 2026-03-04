       IDENTIFICATION DIVISION.
       PROGRAM-ID. IFEQ.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           77 VAL-X PIC 99.
           77 VAL-Y PIC 99.
       PROCEDURE DIVISION.
           MOVE 7 TO VAL-X.
           MOVE 7 TO VAL-Y.
           IF (VAL-X = VAL-Y)
               DISPLAY 'EQUAL'
           ELSE
               DISPLAY 'NOT EQUAL'
           END-IF
           STOP RUN.
