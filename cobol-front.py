#!/usr/bin/env python3
import sys, re

# Regex to match a COBOL level-declaration with PIC and optional VALUE
DECL_RE = re.compile(
    r'^\s*(\d+)\s+'          # level number
    r'(\w+)\s+'              # variable name
    r'PIC\s+([9X]\(\d+\))'   # picture clause, e.g. 9(3) or X(10)
    r'(?:\s+VALUE\s+(".*?"|\S+))?'  # optional VALUE clause
    , re.IGNORECASE
)

def parse_working_storage(lines):
    # find the WS section
    start = next(i for i,l in enumerate(lines) if 'WORKING-STORAGE SECTION' in l)
    end   = next(i for i,l in enumerate(lines) if 'PROCEDURE DIVISION'   in l)
    ws    = lines[start+1:end]

    fields = []
    for l in ws:
        m = DECL_RE.match(l)
        if not m: 
            continue
        lvl, name, pic, val = m.groups()
        # strip quotes from VALUE if present
        if val and val.startswith('"') and val.endswith('"'):
            val = val[1:-1]
        fields.append({
            'level': int(lvl),
            'name': name,
            'pic': pic,
            'value': val or None
        })
    return fields

def parse_procedure(lines):
    idx = next(i for i,l in enumerate(lines) if 'PROCEDURE DIVISION' in l)
    # everything after, strip and skip blank lines
    return [l.strip() for l in lines[idx+1:] if l.strip()]

def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <file.cbl>", file=sys.stderr)
        sys.exit(1)

    lines = open(sys.argv[1]).read().splitlines()

    fields = parse_working_storage(lines)
    print("WORKING-STORAGE FIELDS:")
    for f in fields:
        print(f"  • {f['name']}: level={f['level']}, PIC={f['pic']}, VALUE={f['value']}")

    stmts = parse_procedure(lines)
    print("\nPROCEDURE DIVISION STATEMENTS:")
    for s in stmts:
        print(f"  - {s}")

if __name__ == "__main__":
    main()
