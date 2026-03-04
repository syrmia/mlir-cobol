       IDENTIFICATION DIVISION.
       PROGRAM-ID. IFSIMPLE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           77 NUM-A PIC 99.
           77 NUM-B PIC 99.
       PROCEDURE DIVISION.
           MOVE 10 TO NUM-A.
           MOVE 5 TO NUM-B.
           IF (NUM-A > NUM-B)
               DISPLAY 'A IS GREATER'
           ELSE
               DISPLAY 'B IS GREATER OR EQUAL'
           END-IF
           STOP RUN.
