"""
Parse LLVM IR text into Python dataclasses.

Provides a line-oriented parser that turns ``.ll`` files into a tree of
:class:`Module` / :class:`Function` / :class:`BasicBlock` /
:class:`Instruction` objects suitable for programmatic comparison.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class IRParseError(Exception):
    """Raised when the parser encounters unrecoverable invalid IR."""


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class LLType:
    """Wrapper around a raw LLVM type string."""

    raw: str

    @property
    def is_integer(self) -> bool:
        return bool(re.fullmatch(r"i\d+", self.raw))

    @property
    def is_pointer(self) -> bool:
        return self.raw == "ptr" or self.raw.endswith("*")

    @property
    def is_void(self) -> bool:
        return self.raw == "void"

    @property
    def is_float(self) -> bool:
        return self.raw in ("half", "float", "double", "fp128",
                            "x86_fp80", "ppc_fp128", "bfloat")

    @property
    def bit_width(self) -> int | None:
        """Return bit width for integer types, ``None`` otherwise."""
        m = re.fullmatch(r"i(\d+)", self.raw)
        return int(m.group(1)) if m else None

    def __str__(self) -> str:
        return self.raw


@dataclass
class Operand:
    """An SSA value or constant operand."""

    name: str
    type: LLType | None = None

    def __str__(self) -> str:
        if self.type:
            return f"{self.type} {self.name}"
        return self.name


@dataclass
class Instruction:
    """A single LLVM IR instruction."""

    opcode: str
    result: str | None = None
    result_type: LLType | None = None
    operands: list[Operand] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    predicate: str | None = None
    callee: str | None = None
    call_args: list[Operand] = field(default_factory=list)
    true_label: str | None = None
    false_label: str | None = None
    dest_label: str | None = None
    phi_incoming: list[tuple[str, str]] = field(default_factory=list)
    condition: Operand | None = None
    true_value: Operand | None = None
    false_value: Operand | None = None
    raw: str = ""


@dataclass
class BasicBlock:
    """A basic block with a label and a list of instructions."""

    label: str
    instructions: list[Instruction] = field(default_factory=list)


@dataclass
class Parameter:
    """A function parameter."""

    name: str
    type: LLType


@dataclass
class Function:
    """An LLVM IR function definition or declaration."""

    name: str
    params: list[Parameter] = field(default_factory=list)
    return_type: LLType = field(default_factory=lambda: LLType("void"))
    blocks: list[BasicBlock] = field(default_factory=list)
    is_declaration: bool = False
    linkage: str = ""


@dataclass
class GlobalDecl:
    """A module-level global variable or constant."""

    name: str
    type: LLType | None = None
    is_constant: bool = False
    initializer: str = ""
    linkage: str = ""
    raw: str = ""


@dataclass
class Module:
    """Top-level container for an LLVM IR module."""

    source_filename: str = ""
    target_datalayout: str = ""
    target_triple: str = ""
    globals: list[GlobalDecl] = field(default_factory=list)
    functions: list[Function] = field(default_factory=list)
    declarations: list[Function] = field(default_factory=list)
    type_definitions: dict[str, str] = field(default_factory=dict)

    def get_function(self, name: str) -> Function | None:
        """Return the function with *name*, or ``None``."""
        for fn in self.functions:
            if fn.name == name:
                return fn
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_llvm_ir(path: str | Path) -> Module:
    """Parse a ``.ll`` file at *path* and return a :class:`Module`."""
    text = Path(path).read_text()
    return parse_llvm_ir_string(text)


def parse_llvm_ir_string(text: str) -> Module:
    """Parse an LLVM IR string and return a :class:`Module`."""
    parser = _IRParser(text)
    return parser.parse()


# ---------------------------------------------------------------------------
# Internal parser
# ---------------------------------------------------------------------------

class _IRParser:
    """Line-oriented state-machine parser for LLVM IR text."""

    def __init__(self, text: str) -> None:
        self._lines = text.splitlines()
        self._pos = 0
        self._module = Module()

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _find_matching_paren(s: str, start: int) -> int:
        """Return index of the closing paren matching ``s[start]``."""
        depth = 0
        openers = "([{"
        closers = ")]}"
        for i in range(start, len(s)):
            if s[i] in openers:
                depth += 1
            elif s[i] in closers:
                depth -= 1
                if depth == 0:
                    return i
        return -1

    @staticmethod
    def _split_top_level(s: str, sep: str = ",") -> list[str]:
        """Split *s* by *sep*, respecting parentheses/brackets nesting."""
        parts: list[str] = []
        depth = 0
        cur: list[str] = []
        for ch in s:
            if ch in "([{":
                depth += 1
                cur.append(ch)
            elif ch in ")]}":
                depth -= 1
                cur.append(ch)
            elif ch == sep and depth == 0:
                parts.append("".join(cur).strip())
                cur = []
            else:
                cur.append(ch)
        tail = "".join(cur).strip()
        if tail:
            parts.append(tail)
        return parts

    # -- module-level -------------------------------------------------------

    def parse(self) -> Module:
        while self._pos < len(self._lines):
            line = self._lines[self._pos].strip()
            self._pos += 1

            if not line or line.startswith(";"):
                continue

            if line.startswith("source_filename"):
                m = re.search(r'"(.*?)"', line)
                if m:
                    self._module.source_filename = m.group(1)
            elif line.startswith("target datalayout"):
                m = re.search(r'"(.*?)"', line)
                if m:
                    self._module.target_datalayout = m.group(1)
            elif line.startswith("target triple"):
                m = re.search(r'"(.*?)"', line)
                if m:
                    self._module.target_triple = m.group(1)
            elif line.startswith("%") and "= type" in line:
                name, _, rest = line.partition("= type")
                self._module.type_definitions[name.strip()] = rest.strip()
            elif line.startswith("@"):
                self._parse_global(line)
            elif line.startswith("define"):
                self._parse_function(line)
            elif line.startswith("declare"):
                self._parse_declaration(line)
            elif line.startswith("attributes"):
                continue  # skip attribute groups
            elif line.startswith("!"):
                continue  # skip metadata
            # else: silently ignore unknown top-level lines

        return self._module

    # -- globals ------------------------------------------------------------

    def _parse_global(self, line: str) -> None:
        m = re.match(r"(@[\w.]+)\s*=\s*(.*)", line)
        if not m:
            self._module.globals.append(
                GlobalDecl(name="", raw=line)
            )
            return

        name = m.group(1)
        rest = m.group(2)

        linkage = ""
        for kw in ("private", "internal", "external", "common",
                    "linkonce", "linkonce_odr", "weak", "weak_odr",
                    "appending"):
            if rest.startswith(kw):
                linkage = kw
                rest = rest[len(kw):].strip()
                break

        is_constant = False
        if rest.startswith("constant"):
            is_constant = True
            rest = rest[len("constant"):].strip()
        elif rest.startswith("global"):
            rest = rest[len("global"):].strip()
        elif rest.startswith("unnamed_addr constant"):
            is_constant = True
            rest = rest[len("unnamed_addr constant"):].strip()
        elif rest.startswith("unnamed_addr global"):
            rest = rest[len("unnamed_addr global"):].strip()

        self._module.globals.append(
            GlobalDecl(
                name=name,
                type=LLType(rest.split()[0] if rest.split() else ""),
                is_constant=is_constant,
                initializer=rest,
                linkage=linkage,
                raw=line,
            )
        )

    # -- declarations -------------------------------------------------------

    def _parse_declaration(self, line: str) -> None:
        m = re.search(r"declare\s+(\S+)\s+(@[\w.]+)\s*\(([^)]*)\)", line)
        if not m:
            # Try without return type prefix for void etc.
            m = re.search(r"declare\s+(\S+)\s+(@[\w.]+)", line)
            if m:
                ret_ty = m.group(1)
                fname = m.group(2)
                params: list[Parameter] = []
            else:
                return
        else:
            ret_ty = m.group(1)
            fname = m.group(2)
            params = self._parse_params(m.group(3))

        fn = Function(
            name=fname,
            params=params,
            return_type=LLType(ret_ty),
            is_declaration=True,
        )
        self._module.declarations.append(fn)

    # -- function definitions -----------------------------------------------

    def _parse_function(self, first_line: str) -> None:
        # Collect the full signature which may span multiple lines.
        sig = first_line
        while "{" not in sig and self._pos < len(self._lines):
            sig += " " + self._lines[self._pos].strip()
            self._pos += 1

        # Extract linkage
        linkage = ""
        rest = sig
        m_define = re.match(r"define\s+", rest)
        if m_define:
            rest = rest[m_define.end():]
        for kw in ("private", "internal", "external", "linkonce",
                    "linkonce_odr", "weak", "weak_odr", "common",
                    "dso_local"):
            if rest.startswith(kw + " "):
                linkage = kw
                rest = rest[len(kw):].strip()
                break

        # Skip return attributes (noundef, signext, zeroext, etc.)
        while True:
            stripped = False
            for attr in ("noundef", "signext", "zeroext", "nonnull",
                         "inreg"):
                if rest.startswith(attr + " "):
                    rest = rest[len(attr):].strip()
                    stripped = True
                    break
            if not stripped:
                break

        # Return type and name
        m = re.match(r"(\S+)\s+(@[\w.]+)\s*\(", rest)
        if not m:
            return
        ret_ty = m.group(1)
        fname = m.group(2)

        # Parameters
        paren_start = rest.index("(")
        paren_end = self._find_matching_paren(rest, paren_start)
        param_str = rest[paren_start + 1 : paren_end] if paren_end > 0 else ""
        params = self._parse_params(param_str)

        fn = Function(
            name=fname,
            params=params,
            return_type=LLType(ret_ty),
            linkage=linkage,
        )

        # Parse body until closing '}'
        current_block = BasicBlock(label="entry")
        while self._pos < len(self._lines):
            line = self._lines[self._pos].strip()
            self._pos += 1

            if line == "}":
                break

            if not line or line.startswith(";"):
                continue

            # Label line (e.g. "foo:" or "42:")
            label_m = re.fullmatch(r"([\w.]+):\s*(;.*)?", line)
            if label_m:
                if current_block.instructions or current_block.label != "entry":
                    fn.blocks.append(current_block)
                current_block = BasicBlock(label=label_m.group(1))
                continue

            inst = self._parse_instruction(line)
            current_block.instructions.append(inst)

        fn.blocks.append(current_block)
        self._module.functions.append(fn)

    # -- parameter parsing --------------------------------------------------

    def _parse_params(self, param_str: str) -> list[Parameter]:
        params: list[Parameter] = []
        if not param_str.strip() or param_str.strip() == "...":
            return params
        parts = self._split_top_level(param_str)
        for part in parts:
            part = part.strip()
            if part == "...":
                continue
            tokens = part.split()
            if not tokens:
                continue
            # type might be multi-token (e.g. "i32 noundef %x")
            # Last token starting with % is the name; everything before
            # the name (minus attributes) is the type.
            name = ""
            ty_tokens: list[str] = []
            for t in tokens:
                if t.startswith("%"):
                    name = t
                elif t in ("noundef", "signext", "zeroext", "inreg",
                           "byval", "sret", "noalias", "nocapture",
                           "readonly", "readnone", "nonnull",
                           "dereferenceable", "align"):
                    continue
                else:
                    ty_tokens.append(t)
            ty = " ".join(ty_tokens) if ty_tokens else "i32"
            params.append(Parameter(name=name, type=LLType(ty)))
        return params

    # -- call-argument parsing ----------------------------------------------

    def _parse_call_args(self, args_str: str) -> list[Operand]:
        args: list[Operand] = []
        if not args_str.strip():
            return args
        parts = self._split_top_level(args_str)
        for part in parts:
            part = part.strip()
            if not part:
                continue
            tokens = part.split()
            # Filter attributes
            filtered: list[str] = []
            for t in tokens:
                if t in ("noundef", "signext", "zeroext", "inreg",
                         "noalias", "nocapture", "readonly"):
                    continue
                filtered.append(t)
            if len(filtered) >= 2:
                ty = " ".join(filtered[:-1])
                val = filtered[-1]
            elif len(filtered) == 1:
                ty = ""
                val = filtered[0]
            else:
                continue
            args.append(Operand(name=val, type=LLType(ty) if ty else None))
        return args

    # -- instruction parsing ------------------------------------------------

    def _parse_instruction(self, line: str) -> Instruction:
        """Dispatch to an opcode-specific handler."""
        raw = line

        # Strip trailing comments.
        # Be careful not to strip inside string constants.
        comment_idx = line.find(";")
        if comment_idx > 0:
            line = line[:comment_idx].rstrip()

        # Detect assignment:  %result = <rest>
        result_name: str | None = None
        rest = line
        assign_m = re.match(r"(%[\w.]+)\s*=\s*(.*)", line)
        if assign_m:
            result_name = assign_m.group(1)
            rest = assign_m.group(2)

        # First token is the opcode.
        tokens = rest.split(None, 1)
        if not tokens:
            return Instruction(opcode="<unparsed>", raw=raw)
        opcode = tokens[0]
        remainder = tokens[1] if len(tokens) > 1 else ""

        try:
            handler = getattr(self, f"_inst_{opcode}", None)
            if handler:
                inst = handler(result_name, remainder, raw)
                return inst
            # Generic fallback for unknown opcodes.
            return self._inst_generic(opcode, result_name, remainder, raw)
        except Exception:
            return Instruction(opcode="<unparsed>", raw=raw)

    # -- arithmetic / bitwise -----------------------------------------------

    def _inst_binary(self, opcode: str, result: str | None,
                     remainder: str, raw: str) -> Instruction:
        """Parse binary ops like ``add nsw i32 %a, %b``."""
        flags: list[str] = []
        tokens = remainder.split()
        idx = 0
        # Collect flags (nsw, nuw, exact, fast, nnan, ninf, etc.)
        while idx < len(tokens) and tokens[idx] in (
                "nsw", "nuw", "exact", "fast", "nnan", "ninf",
                "nsz", "arcp", "contract", "afn", "reassoc"):
            flags.append(tokens[idx])
            idx += 1
        # Next token is the type.
        ty = tokens[idx] if idx < len(tokens) else ""
        # The rest is "op1, op2"
        operand_str = " ".join(tokens[idx + 1:])
        parts = [p.strip() for p in operand_str.split(",")]
        operands = [Operand(name=p, type=LLType(ty)) for p in parts if p]

        return Instruction(
            opcode=opcode,
            result=result,
            result_type=LLType(ty),
            operands=operands,
            flags=flags,
            raw=raw,
        )

    # Map all binary opcodes to the shared handler.
    def _inst_add(self, r, rem, raw): return self._inst_binary("add", r, rem, raw)
    def _inst_sub(self, r, rem, raw): return self._inst_binary("sub", r, rem, raw)
    def _inst_mul(self, r, rem, raw): return self._inst_binary("mul", r, rem, raw)
    def _inst_sdiv(self, r, rem, raw): return self._inst_binary("sdiv", r, rem, raw)
    def _inst_udiv(self, r, rem, raw): return self._inst_binary("udiv", r, rem, raw)
    def _inst_srem(self, r, rem, raw): return self._inst_binary("srem", r, rem, raw)
    def _inst_urem(self, r, rem, raw): return self._inst_binary("urem", r, rem, raw)
    def _inst_and(self, r, rem, raw): return self._inst_binary("and", r, rem, raw)
    def _inst_or(self, r, rem, raw): return self._inst_binary("or", r, rem, raw)
    def _inst_xor(self, r, rem, raw): return self._inst_binary("xor", r, rem, raw)
    def _inst_shl(self, r, rem, raw): return self._inst_binary("shl", r, rem, raw)
    def _inst_lshr(self, r, rem, raw): return self._inst_binary("lshr", r, rem, raw)
    def _inst_ashr(self, r, rem, raw): return self._inst_binary("ashr", r, rem, raw)
    def _inst_fadd(self, r, rem, raw): return self._inst_binary("fadd", r, rem, raw)
    def _inst_fsub(self, r, rem, raw): return self._inst_binary("fsub", r, rem, raw)
    def _inst_fmul(self, r, rem, raw): return self._inst_binary("fmul", r, rem, raw)
    def _inst_fdiv(self, r, rem, raw): return self._inst_binary("fdiv", r, rem, raw)
    def _inst_frem(self, r, rem, raw): return self._inst_binary("frem", r, rem, raw)

    # -- comparison ---------------------------------------------------------

    def _inst_icmp(self, result, remainder, raw):
        tokens = remainder.split()
        pred = tokens[0] if tokens else ""
        ty = tokens[1] if len(tokens) > 1 else ""
        operand_str = " ".join(tokens[2:])
        parts = [p.strip() for p in operand_str.split(",")]
        operands = [Operand(name=p, type=LLType(ty)) for p in parts if p]
        return Instruction(
            opcode="icmp", result=result, result_type=LLType("i1"),
            operands=operands, predicate=pred, raw=raw,
        )

    def _inst_fcmp(self, result, remainder, raw):
        tokens = remainder.split()
        pred = tokens[0] if tokens else ""
        ty = tokens[1] if len(tokens) > 1 else ""
        operand_str = " ".join(tokens[2:])
        parts = [p.strip() for p in operand_str.split(",")]
        operands = [Operand(name=p, type=LLType(ty)) for p in parts if p]
        return Instruction(
            opcode="fcmp", result=result, result_type=LLType("i1"),
            operands=operands, predicate=pred, raw=raw,
        )

    # -- branch -------------------------------------------------------------

    def _inst_br(self, result, remainder, raw):
        tokens = remainder.split()
        if tokens and tokens[0] == "i1":
            # Conditional: br i1 %cond, label %true, label %false
            cond_name = tokens[1].rstrip(",") if len(tokens) > 1 else ""
            true_label = ""
            false_label = ""
            for i, t in enumerate(tokens):
                if t == "label":
                    lbl = tokens[i + 1].rstrip(",") if i + 1 < len(tokens) else ""
                    if not true_label:
                        true_label = lbl
                    else:
                        false_label = lbl
            return Instruction(
                opcode="br", result=result,
                condition=Operand(name=cond_name, type=LLType("i1")),
                true_label=true_label, false_label=false_label, raw=raw,
            )
        else:
            # Unconditional: br label %dest
            dest = ""
            for i, t in enumerate(tokens):
                if t == "label" and i + 1 < len(tokens):
                    dest = tokens[i + 1]
                    break
            return Instruction(
                opcode="br", result=result,
                dest_label=dest, raw=raw,
            )

    # -- return -------------------------------------------------------------

    def _inst_ret(self, result, remainder, raw):
        remainder = remainder.strip()
        if remainder == "void":
            return Instruction(opcode="ret", result_type=LLType("void"), raw=raw)
        tokens = remainder.split(None, 1)
        ty = tokens[0] if tokens else ""
        val = tokens[1] if len(tokens) > 1 else ""
        return Instruction(
            opcode="ret", result_type=LLType(ty),
            operands=[Operand(name=val, type=LLType(ty))] if val else [],
            raw=raw,
        )

    # -- call ---------------------------------------------------------------

    def _inst_call(self, result, remainder, raw):
        # Strip optional tail/musttail/notail prefixes
        for prefix in ("tail ", "musttail ", "notail "):
            if remainder.startswith(prefix):
                remainder = remainder[len(prefix):]

        # Find callee and args: ... @name(args)
        paren_idx = remainder.find("(")
        if paren_idx < 0:
            return Instruction(opcode="call", result=result, raw=raw)

        prefix = remainder[:paren_idx].strip()
        # Callee is the last token before '('
        prefix_tokens = prefix.split()
        callee = prefix_tokens[-1] if prefix_tokens else ""
        # Return type is everything before the callee
        ret_ty = " ".join(prefix_tokens[:-1]) if len(prefix_tokens) > 1 else ""

        # Extract args between matching parens
        end_paren = self._find_matching_paren(remainder, paren_idx)
        args_str = remainder[paren_idx + 1 : end_paren] if end_paren > 0 else ""
        call_args = self._parse_call_args(args_str)

        return Instruction(
            opcode="call", result=result,
            result_type=LLType(ret_ty) if ret_ty else None,
            callee=callee, call_args=call_args, raw=raw,
        )

    # -- alloca -------------------------------------------------------------

    def _inst_alloca(self, result, remainder, raw):
        tokens = remainder.split(",")
        ty = tokens[0].strip() if tokens else ""
        return Instruction(
            opcode="alloca", result=result,
            result_type=LLType("ptr"),
            operands=[Operand(name=ty, type=LLType(ty))],
            raw=raw,
        )

    # -- load ---------------------------------------------------------------

    def _inst_load(self, result, remainder, raw):
        parts = remainder.split(",")
        ty = parts[0].strip() if parts else ""
        ptr = parts[1].strip() if len(parts) > 1 else ""
        ptr_tokens = ptr.split()
        ptr_name = ptr_tokens[-1] if ptr_tokens else ""
        return Instruction(
            opcode="load", result=result, result_type=LLType(ty),
            operands=[Operand(name=ptr_name, type=LLType("ptr"))],
            raw=raw,
        )

    # -- store --------------------------------------------------------------

    def _inst_store(self, result, remainder, raw):
        parts = self._split_top_level(remainder)
        val_tokens = parts[0].split() if parts else []
        ptr_tokens = parts[1].split() if len(parts) > 1 else []
        val_ty = val_tokens[0] if val_tokens else ""
        val_name = val_tokens[-1] if val_tokens else ""
        ptr_name = ptr_tokens[-1] if ptr_tokens else ""
        return Instruction(
            opcode="store", result=result,
            operands=[
                Operand(name=val_name, type=LLType(val_ty)),
                Operand(name=ptr_name, type=LLType("ptr")),
            ],
            raw=raw,
        )

    # -- getelementptr ------------------------------------------------------

    def _inst_getelementptr(self, result, remainder, raw):
        # getelementptr [inbounds] <ty>, ptr %base, <idx>...
        flags: list[str] = []
        if remainder.startswith("inbounds "):
            flags.append("inbounds")
            remainder = remainder[len("inbounds "):]
        parts = self._split_top_level(remainder)
        operands: list[Operand] = []
        base_ty = parts[0].strip() if parts else ""
        for p in parts[1:]:
            toks = p.strip().split()
            ty = toks[0] if toks else ""
            name = toks[-1] if toks else ""
            operands.append(Operand(name=name, type=LLType(ty)))
        return Instruction(
            opcode="getelementptr", result=result,
            result_type=LLType("ptr"),
            operands=operands, flags=flags, raw=raw,
        )

    # -- phi ----------------------------------------------------------------

    def _inst_phi(self, result, remainder, raw):
        # phi i32 [ %val1, %bb1 ], [ %val2, %bb2 ], ...
        tokens = remainder.split(None, 1)
        ty = tokens[0] if tokens else ""
        rest = tokens[1] if len(tokens) > 1 else ""

        incoming: list[tuple[str, str]] = []
        for m in re.finditer(r"\[\s*([^,\]]+)\s*,\s*([^\]]+)\s*\]", rest):
            incoming.append((m.group(1).strip(), m.group(2).strip()))

        return Instruction(
            opcode="phi", result=result, result_type=LLType(ty),
            phi_incoming=incoming, raw=raw,
        )

    # -- select -------------------------------------------------------------

    def _inst_select(self, result, remainder, raw):
        # select i1 %cond, i32 %a, i32 %b
        parts = self._split_top_level(remainder)
        cond = true_val = false_val = None
        if len(parts) >= 3:
            ct = parts[0].split()
            cond = Operand(name=ct[-1] if ct else "", type=LLType(ct[0] if ct else "i1"))
            tt = parts[1].split()
            true_val = Operand(name=tt[-1] if tt else "", type=LLType(tt[0] if tt else ""))
            ft = parts[2].split()
            false_val = Operand(name=ft[-1] if ft else "", type=LLType(ft[0] if ft else ""))
        ty = true_val.type if true_val and true_val.type else LLType("")
        return Instruction(
            opcode="select", result=result, result_type=ty,
            condition=cond, true_value=true_val, false_value=false_val,
            raw=raw,
        )

    # -- casts --------------------------------------------------------------

    def _inst_cast(self, opcode, result, remainder, raw):
        # sext i8 %x to i32
        m = re.match(r"(\S+)\s+(\S+)\s+to\s+(\S+)", remainder)
        if m:
            src_ty, src_val, dst_ty = m.group(1), m.group(2), m.group(3)
            return Instruction(
                opcode=opcode, result=result,
                result_type=LLType(dst_ty),
                operands=[Operand(name=src_val, type=LLType(src_ty))],
                raw=raw,
            )
        return Instruction(opcode=opcode, result=result, raw=raw)

    def _inst_sext(self, r, rem, raw): return self._inst_cast("sext", r, rem, raw)
    def _inst_zext(self, r, rem, raw): return self._inst_cast("zext", r, rem, raw)
    def _inst_trunc(self, r, rem, raw): return self._inst_cast("trunc", r, rem, raw)
    def _inst_bitcast(self, r, rem, raw): return self._inst_cast("bitcast", r, rem, raw)
    def _inst_sitofp(self, r, rem, raw): return self._inst_cast("sitofp", r, rem, raw)
    def _inst_fptosi(self, r, rem, raw): return self._inst_cast("fptosi", r, rem, raw)
    def _inst_uitofp(self, r, rem, raw): return self._inst_cast("uitofp", r, rem, raw)
    def _inst_fptoui(self, r, rem, raw): return self._inst_cast("fptoui", r, rem, raw)
    def _inst_fpext(self, r, rem, raw): return self._inst_cast("fpext", r, rem, raw)
    def _inst_fptrunc(self, r, rem, raw): return self._inst_cast("fptrunc", r, rem, raw)
    def _inst_inttoptr(self, r, rem, raw): return self._inst_cast("inttoptr", r, rem, raw)
    def _inst_ptrtoint(self, r, rem, raw): return self._inst_cast("ptrtoint", r, rem, raw)
    def _inst_addrspacecast(self, r, rem, raw): return self._inst_cast("addrspacecast", r, rem, raw)

    # -- switch -------------------------------------------------------------

    def _inst_switch(self, result, remainder, raw):
        return Instruction(opcode="switch", result=result, raw=raw)

    # -- unreachable --------------------------------------------------------

    def _inst_unreachable(self, result, remainder, raw):
        return Instruction(opcode="unreachable", raw=raw)

    # -- generic fallback ---------------------------------------------------

    def _inst_generic(self, opcode: str, result: str | None,
                      remainder: str, raw: str) -> Instruction:
        return Instruction(opcode=opcode, result=result, raw=raw)
