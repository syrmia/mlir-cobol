            IDENTIFICATION DIVISION.
            PROGRAM-ID. SIMPLE-STRUCT.
            DATA DIVISION.
      
              *> create a single record
              WORKING-STORAGE SECTION.
                01 TRANSACTION-RECORD.
                  02 UID PIC 9(5) VALUE 12345.
                  02 DESC PIC X(25) VALUE 'TEST TRANSACTION'.

                01 FIRST-VAR  PIC 9(2).
                01 SECOND-VAR PIC S9(2)V9(2).

            PROCEDURE DIVISION.
              *> print the record we are writing
              DISPLAY 'WRITING RECORD: 'TRANSACTION-RECORD.
              STOP RUN.
      