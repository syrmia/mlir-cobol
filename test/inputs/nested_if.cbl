       IDENTIFICATION DIVISION.
       PROGRAM-ID. NESTEDIF.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           77 NUM-A PIC 99.
           77 NUM-B PIC 99.
       PROCEDURE DIVISION.
           MOVE 10 TO NUM-A.
           MOVE 5 TO NUM-B.
           IF (NUM-A > NUM-B)
               IF (NUM-A > 8)
                   DISPLAY 'A > B AND A > 8'
               ELSE
                   DISPLAY 'A > B BUT A <= 8'
               END-IF
           ELSE
               DISPLAY 'A <= B'
           END-IF
           STOP RUN.
