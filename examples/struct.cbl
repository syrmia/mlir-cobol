            IDENTIFICATION DIVISION.
            PROGRAM-ID. STRUCT.
            DATA DIVISION.
      
              *> create a single record
              WORKING-STORAGE SECTION.
                01 TRANSACTION-RECORD.
                  02 UID PIC 9(5) VALUE 12345.
                  02 DESC PIC X(25) VALUE 'TEST TRANSACTION'.
                  02 DETAILS.
                    03 AMOUNT PIC 9(6)V9(2) VALUE 000124.34.
                    03 START-BALANCE PIC 9(6)V9(2) VALUE 000177.54.
                    03 END-BALANCE PIC 9(6)V9(2) VALUE 53.2.
                  02 ACCOUNT-ID PIC 9(7).
                  02 ACCOUNT-HOLDER PIC A(50).

            PROCEDURE DIVISION.
              *> print the record we are writing
              DISPLAY 'WRITING RECORD: 'TRANSACTION-RECORD.
              STOP RUN.
      