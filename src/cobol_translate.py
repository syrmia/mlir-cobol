#!/usr/bin/env python3
"""
cobol-translate: COBOL to MLIR translation tool
"""

import argparse
import os
import sys
from pathlib import Path

from cobol_front import run_koopa, read_xml, emit_cobol_mlir
from emitc_lowering import lower_to_emitc


def check_koopa():
    """Check if KOOPA_PATH is set and koopa.jar exists."""
    koopa_path = os.environ.get("KOOPA_PATH", "")
    if not koopa_path:
        sys.exit(
            "Error: KOOPA_PATH environment variable is not set.\n"
            "Please set it to the directory containing koopa.jar:\n"
            "  export KOOPA_PATH=/path/to/koopa\n\n"
            "To download koopa.jar:\n"
            "  wget https://github.com/krisds/koopa/releases/download/v20250222/koopa-20250222.jar -O koopa.jar"
        )

    koopa_jar = Path(koopa_path) / "koopa.jar"
    if not koopa_jar.exists():
        sys.exit(
            f"Error: koopa.jar not found at '{koopa_jar}'\n"
            "Please download it:\n"
            f"  wget https://github.com/krisds/koopa/releases/download/v20250222/koopa-20250222.jar -O {koopa_jar}"
        )


def main():
    parser = argparse.ArgumentParser(
        prog='cobol-translate',
        description='Translate COBOL source files to MLIR'
    )
    parser.add_argument(
        'input',
        type=Path,
        help='Input COBOL source file (.cbl)'
    )
    parser.add_argument(
        '--emit',
        choices=['cobol-mlir', 'emitc', 'llvm-mlir'],
        default='cobol-mlir',
        help='Output format (default: cobol-mlir)'
    )
    parser.add_argument(
        '-o', '--output',
        type=Path,
        help='Output file (default: stdout)'
    )

    args = parser.parse_args()

    # Check KOOPA_PATH before proceeding
    check_koopa()

    if not args.input.exists():
        sys.exit(f"Error: Input file '{args.input}' not found")

    # Parse COBOL to XML using KOOPA
    run_koopa(args.input)

    # Read XML and convert to internal representation
    lines = read_xml(args.input)

    # Generate MLIR
    module = emit_cobol_mlir(lines)

    if args.emit == 'cobol-mlir':
        output = str(module)
    elif args.emit == 'emitc':
        result = lower_to_emitc(module)
        if result is None:
            sys.exit(1)
        output = str(result)
    elif args.emit == 'llvm-mlir':
        sys.exit("Error: --emit=llvm-mlir not yet implemented")

    # Output
    if args.output:
        args.output.write_text(output)
    else:
        print(output)


if __name__ == "__main__":
    main()
