            IDENTIFICATION DIVISION.
            PROGRAM-ID. SIMPLE-STRUCT.
            DATA DIVISION.
      
              *> create a single record
              WORKING-STORAGE SECTION.
                01 TRANSACTION-RECORD.
                  02 UID PIC 9(5) VALUE 12345.
                  02 DESC PIC X(25) VALUE 'TEST TRANSACTION'.

            PROCEDURE DIVISION.
              *> print the record we are writing
              DISPLAY 'WRITING RECORD: 'TRANSACTION-RECORD.
              STOP RUN.
      