IDENTIFICATION   DIVISION.
PROGRAM-ID.      prog.
DATA             DIVISION.
WORKING-STORAGE  SECTION.
       01 X             PIC X value "value1".
       01 Y             PIC X value "value2".
PROCEDURE        DIVISION.
    DISPLAY X, Y ADVANCING
    END-DISPLAY.
    STOP RUN.