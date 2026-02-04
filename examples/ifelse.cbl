       IDENTIFICATION DIVISION.
       PROGRAM-ID. HELLOWORD.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           77 OPERAND1 PIC 99.
           77 OPERAND2 PIC 99.
       PROCEDURE DIVISION.
           MOVE 10 TO OPERAND1.
           MOVE 8 TO OPERAND2.
           IF OPERAND1 > OPERAND2
               DISPLAY 'OPERAND2 is smaller than OPERAND1'
           ELSE
               DISPLAY 'OPERAND2 is not smaller or numeric'
           END-IF
           STOP RUN.
