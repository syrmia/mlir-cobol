"""
Static semantic fingerprinting for LLVM IR modules.

Extracts five semantic features from parsed LLVM IR, compares them
pairwise, and produces a weighted similarity score in [0.0, 1.0].

Features:
  - I/O sequence (cin/cout calls with operand types)
  - Computation DAG (topological signature from SSA def-use chains)
  - CFG shape (node/edge/back-edge counts + degree sequence)
  - Operation histogram (opcode frequency counts)
  - Type signature (return type + parameter types)
"""

from __future__ import annotations

import math
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from semantic_equiv.ir_parser import (
    BasicBlock,
    Function,
    Instruction,
    Module,
    Operand,
    parse_llvm_ir,
    parse_llvm_ir_string,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_WEIGHTS = {
    "io_sequence": 0.30,
    "computation_dag": 0.30,
    "cfg_shape": 0.20,
    "op_histogram": 0.15,
    "type_signature": 0.05,
}

# I/O detection regex patterns for mangled C++ names.
_OUTPUT_PATTERNS = [
    re.compile(r"_ZNSolsE"),     # ostream::operator<< (member)
    re.compile(r"_ZStlsI"),      # operator<< (free template)
    re.compile(r"_ZNSolsE\w+"),  # ostream::operator<< with type suffix
]
_INPUT_PATTERNS = [
    re.compile(r"_ZNSirsE"),     # istream::operator>> (member)
    re.compile(r"_ZStrsI"),      # operator>> (free template)
]
_IO_SKIP_PATTERNS = [
    re.compile(r"_ZNSo5flushE"),  # ostream::flush
    re.compile(r"_ZNSo3putE"),    # ostream::put
]

# Mangled type suffix mapping.
_MANGLED_TYPE_MAP = {
    "i": "i32",
    "l": "i64",
    "d": "double",
    "f": "float",
    "c": "i8",
    "s": "i16",
    "b": "i1",
    "x": "i64",
    "j": "i32",
    "m": "i64",
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class IOOperation:
    """A single I/O operation (cin or cout call)."""
    direction: str  # "input" or "output"
    operand_type: str
    callee: str


@dataclass
class IOSequence:
    """Ordered list of I/O operations in a function."""
    operations: list[IOOperation] = field(default_factory=list)


@dataclass
class OpHistogram:
    """Opcode frequency counts for a function."""
    counts: dict[str, int] = field(default_factory=dict)


@dataclass
class CFGShape:
    """Control-flow graph shape features."""
    num_nodes: int = 0
    num_edges: int = 0
    num_back_edges: int = 0
    max_loop_depth: int = 0
    node_degree_sequence: list[int] = field(default_factory=list)


@dataclass
class ComputationDAGFeatures:
    """Features extracted from the SSA def-use computation DAG."""
    depth: int = 0
    num_nodes: int = 0
    width_sequence: list[int] = field(default_factory=list)
    opcode_counts: dict[str, int] = field(default_factory=dict)
    leaf_type_counts: dict[str, int] = field(default_factory=dict)
    root_count: int = 0


@dataclass
class TypeSignature:
    """Function type signature: return type + parameter types."""
    return_type: str = "void"
    param_types: list[str] = field(default_factory=list)


@dataclass
class FunctionFingerprint:
    """Complete fingerprint for a single function."""
    function_name: str = ""
    io_sequence: IOSequence = field(default_factory=IOSequence)
    op_histogram: OpHistogram = field(default_factory=OpHistogram)
    cfg_shape: CFGShape = field(default_factory=CFGShape)
    computation_dag: ComputationDAGFeatures = field(
        default_factory=ComputationDAGFeatures
    )
    type_signature: TypeSignature = field(default_factory=TypeSignature)


@dataclass
class ModuleFingerprint:
    """Fingerprints for all functions in a module."""
    function_fingerprints: dict[str, FunctionFingerprint] = field(
        default_factory=dict
    )


@dataclass
class FeatureScores:
    """Per-feature similarity scores."""
    io_sequence: float = 0.0
    computation_dag: float = 0.0
    cfg_shape: float = 0.0
    op_histogram: float = 0.0
    type_signature: float = 0.0


@dataclass
class FingerprintResult:
    """Result of comparing two module fingerprints."""
    overall_score: float = 0.0
    feature_scores: FeatureScores = field(default_factory=FeatureScores)
    weights: dict[str, float] = field(default_factory=dict)
    matched_functions: list[str] = field(default_factory=list)
    unmatched_a: list[str] = field(default_factory=list)
    unmatched_b: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _cosine_similarity(vec_a: dict[str, int | float],
                       vec_b: dict[str, int | float]) -> float:
    """Compute cosine similarity between two sparse vectors.

    Returns 1.0 for two empty vectors (both are the zero vector).
    """
    if not vec_a and not vec_b:
        return 1.0

    all_keys = set(vec_a) | set(vec_b)
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for key in all_keys:
        a_val = vec_a.get(key, 0)
        b_val = vec_b.get(key, 0)
        dot += a_val * b_val
        norm_a += a_val * a_val
        norm_b += b_val * b_val

    if norm_a == 0 and norm_b == 0:
        return 1.0  # Both zero vectors are identical.
    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


def _levenshtein_distance(seq_a: list[str], seq_b: list[str]) -> int:
    """Compute Levenshtein distance between two sequences of strings.

    Uses 2-row optimized DP.
    """
    m, n = len(seq_a), len(seq_b)
    if m == 0:
        return n
    if n == 0:
        return m

    prev = list(range(n + 1))
    curr = [0] * (n + 1)

    for i in range(1, m + 1):
        curr[0] = i
        for j in range(1, n + 1):
            cost = 0 if seq_a[i - 1] == seq_b[j - 1] else 1
            curr[j] = min(
                curr[j - 1] + 1,       # insertion
                prev[j] + 1,           # deletion
                prev[j - 1] + cost,    # substitution
            )
        prev, curr = curr, prev

    return prev[n]


def _ratio_similarity(a: int, b: int) -> float:
    """Compute ratio-based similarity: 1.0 - abs(a-b)/max(a,b,1)."""
    return 1.0 - abs(a - b) / max(a, b, 1)


def _sequence_cosine(seq_a: list[int], seq_b: list[int]) -> float:
    """Compute cosine similarity between two integer sequences.

    Pads the shorter sequence with zeros.
    """
    if not seq_a and not seq_b:
        return 1.0

    max_len = max(len(seq_a), len(seq_b))
    a_padded = seq_a + [0] * (max_len - len(seq_a))
    b_padded = seq_b + [0] * (max_len - len(seq_b))

    dot = sum(x * y for x, y in zip(a_padded, b_padded))
    norm_a = math.sqrt(sum(x * x for x in a_padded))
    norm_b = math.sqrt(sum(x * x for x in b_padded))

    if norm_a == 0 and norm_b == 0:
        return 1.0  # Both zero vectors are identical.
    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot / (norm_a * norm_b)


def _classify_io_call(callee: str,
                      call_args: list[Operand]) -> Optional[IOOperation]:
    """Classify a call instruction as an I/O operation, or return None."""
    if not callee:
        return None

    # Skip flush/put mechanics.
    for pat in _IO_SKIP_PATTERNS:
        if pat.search(callee):
            return None

    # Check output patterns.
    for pat in _OUTPUT_PATTERNS:
        if pat.search(callee):
            op_type = _infer_io_type(callee, call_args)
            return IOOperation(direction="output", operand_type=op_type,
                               callee=callee)

    # Check input patterns.
    for pat in _INPUT_PATTERNS:
        if pat.search(callee):
            op_type = _infer_io_type(callee, call_args)
            return IOOperation(direction="input", operand_type=op_type,
                               callee=callee)

    return None


def _infer_io_type(callee: str, call_args: list[Operand]) -> str:
    """Infer the I/O operand type from mangled name or call arguments."""
    # Try to get type from the last character of the mangled member name.
    # E.g., _ZNSolsEi -> 'i' -> i32
    m = re.search(r"_ZN\w+E(\w)$", callee)
    if m:
        suffix = m.group(1)
        if suffix in _MANGLED_TYPE_MAP:
            return _MANGLED_TYPE_MAP[suffix]

    # Fallback: examine call_args types.
    for arg in call_args:
        if arg.type and arg.type.raw and arg.type.raw not in ("ptr", ""):
            return arg.type.raw

    return "unknown"


def _get_terminator(block: BasicBlock) -> Optional[Instruction]:
    """Return the last instruction in a block (the terminator)."""
    if block.instructions:
        return block.instructions[-1]
    return None


def _normalize_label(label: str) -> str:
    """Strip leading '%' from a label."""
    if label.startswith("%"):
        return label[1:]
    return label


# ---------------------------------------------------------------------------
# Feature extractors
# ---------------------------------------------------------------------------

def extract_io_sequence(fn: Function) -> IOSequence:
    """Extract the ordered I/O sequence from a function."""
    ops: list[IOOperation] = []
    for block in fn.blocks:
        for inst in block.instructions:
            if inst.opcode == "call" and inst.callee:
                io_op = _classify_io_call(inst.callee, inst.call_args)
                if io_op is not None:
                    ops.append(io_op)
    return IOSequence(operations=ops)


def extract_op_histogram(fn: Function) -> OpHistogram:
    """Extract opcode frequency counts across all blocks."""
    counts: dict[str, int] = {}
    for block in fn.blocks:
        for inst in block.instructions:
            opcode = inst.opcode
            if opcode and opcode != "<unparsed>":
                counts[opcode] = counts.get(opcode, 0) + 1
    return OpHistogram(counts=counts)


def extract_cfg_shape(fn: Function) -> CFGShape:
    """Extract CFG shape features using DFS for back-edge detection."""
    if not fn.blocks:
        return CFGShape()

    # Build label -> index mapping.
    label_to_idx: dict[str, int] = {}
    for i, block in enumerate(fn.blocks):
        label_to_idx[block.label] = i

    num_nodes = len(fn.blocks)

    # Build adjacency list from terminators.
    adj: list[list[int]] = [[] for _ in range(num_nodes)]
    for i, block in enumerate(fn.blocks):
        term = _get_terminator(block)
        if term is None:
            continue

        targets: list[str] = []
        if term.opcode == "br":
            if term.dest_label:
                targets.append(_normalize_label(term.dest_label))
            if term.true_label:
                targets.append(_normalize_label(term.true_label))
            if term.false_label:
                targets.append(_normalize_label(term.false_label))
        elif term.opcode == "switch":
            # Switch targets are not fully parsed; skip for now.
            pass

        for target in targets:
            j = label_to_idx.get(target)
            if j is not None:
                adj[i].append(j)

    # Count edges.
    num_edges = sum(len(successors) for successors in adj)

    # DFS for back-edges with WHITE/GRAY/BLACK coloring.
    WHITE, GRAY, BLACK = 0, 1, 2
    color = [WHITE] * num_nodes
    num_back_edges = 0
    max_depth = 0

    def dfs(node: int, depth: int) -> None:
        nonlocal num_back_edges, max_depth
        color[node] = GRAY
        if depth > max_depth:
            max_depth = depth
        for succ in adj[node]:
            if color[succ] == GRAY:
                num_back_edges += 1
            elif color[succ] == WHITE:
                dfs(succ, depth + 1)
        color[node] = BLACK

    # Start DFS from entry block (index 0).
    dfs(0, 0)

    # Also visit any unreachable blocks.
    for i in range(num_nodes):
        if color[i] == WHITE:
            dfs(i, 0)

    # Compute degree sequence (in-degree + out-degree for each node).
    in_degree = [0] * num_nodes
    for i in range(num_nodes):
        for j in adj[i]:
            in_degree[j] += 1

    degree_sequence = sorted(
        [in_degree[i] + len(adj[i]) for i in range(num_nodes)],
        reverse=True,
    )

    return CFGShape(
        num_nodes=num_nodes,
        num_edges=num_edges,
        num_back_edges=num_back_edges,
        max_loop_depth=max_depth,
        node_degree_sequence=degree_sequence,
    )


def extract_computation_dag(fn: Function) -> ComputationDAGFeatures:
    """Extract computation DAG features from SSA def-use chains."""
    if not fn.blocks:
        return ComputationDAGFeatures()

    # Build def_map: ssa_name -> (opcode, operand_names).
    def_map: dict[str, tuple[str, list[str]]] = {}
    all_used: set[str] = set()

    for block in fn.blocks:
        for inst in block.instructions:
            if inst.result:
                operand_names: list[str] = []
                for op in inst.operands:
                    operand_names.append(op.name)
                    all_used.add(op.name)
                # Also include call_args.
                for arg in inst.call_args:
                    operand_names.append(arg.name)
                    all_used.add(arg.name)
                # Phi incoming values.
                for val, _label in inst.phi_incoming:
                    operand_names.append(val)
                    all_used.add(val)
                # Select operands.
                if inst.condition:
                    operand_names.append(inst.condition.name)
                    all_used.add(inst.condition.name)
                if inst.true_value:
                    operand_names.append(inst.true_value.name)
                    all_used.add(inst.true_value.name)
                if inst.false_value:
                    operand_names.append(inst.false_value.name)
                    all_used.add(inst.false_value.name)

                def_map[inst.result] = (inst.opcode, operand_names)

    if not def_map:
        return ComputationDAGFeatures()

    # Compute depth per node via memoized recursion.
    # Sentinel value -1 breaks phi cycles.
    depth_cache: dict[str, int] = {}
    COMPUTING = -1

    def compute_depth(name: str) -> int:
        if name in depth_cache:
            val = depth_cache[name]
            if val == COMPUTING:
                return 0  # Break cycle.
            return val

        if name not in def_map:
            # Leaf node (parameter or constant).
            depth_cache[name] = 0
            return 0

        depth_cache[name] = COMPUTING
        opcode, operand_names = def_map[name]
        max_op_depth = 0
        for op_name in operand_names:
            d = compute_depth(op_name)
            if d > max_op_depth:
                max_op_depth = d
        result_depth = 1 + max_op_depth
        depth_cache[name] = result_depth
        return result_depth

    # Compute depths for all defined nodes.
    for name in def_map:
        compute_depth(name)

    # Gather features.
    num_nodes = len(def_map)
    max_depth = max((d for d in depth_cache.values() if d >= 0), default=0)

    # Width sequence: count of nodes at each depth level.
    width_at_depth: dict[int, int] = {}
    for name in def_map:
        d = depth_cache.get(name, 0)
        if d >= 0:
            width_at_depth[d] = width_at_depth.get(d, 0) + 1

    width_sequence = [width_at_depth.get(i, 0) for i in range(max_depth + 1)]

    # Opcode counts.
    opcode_counts: dict[str, int] = {}
    for opcode, _ in def_map.values():
        opcode_counts[opcode] = opcode_counts.get(opcode, 0) + 1

    # Leaf type counts: types of operands that are not in def_map.
    leaf_type_counts: dict[str, int] = {}
    for _opcode, operand_names in def_map.values():
        for op_name in operand_names:
            if op_name not in def_map:
                # Classify leaf type.
                if op_name.startswith("%"):
                    leaf_type = "param"
                elif op_name.startswith("@"):
                    leaf_type = "global"
                else:
                    leaf_type = "constant"
                leaf_type_counts[leaf_type] = (
                    leaf_type_counts.get(leaf_type, 0) + 1
                )

    # Root count: nodes whose result is not used by any other instruction.
    defined_names = set(def_map.keys())
    root_count = 0
    for name in defined_names:
        if name not in all_used:
            root_count += 1

    return ComputationDAGFeatures(
        depth=max_depth,
        num_nodes=num_nodes,
        width_sequence=width_sequence,
        opcode_counts=opcode_counts,
        leaf_type_counts=leaf_type_counts,
        root_count=root_count,
    )


def extract_type_signature(fn: Function) -> TypeSignature:
    """Extract the function type signature."""
    return TypeSignature(
        return_type=fn.return_type.raw,
        param_types=[p.type.raw for p in fn.params],
    )


# ---------------------------------------------------------------------------
# Feature comparators
# ---------------------------------------------------------------------------

def compare_io_sequences(a: IOSequence, b: IOSequence) -> float:
    """Compare two I/O sequences using normalized Levenshtein distance."""
    if not a.operations and not b.operations:
        return 1.0

    # Build canonical string representations.
    seq_a = [f"{op.direction}:{op.operand_type}" for op in a.operations]
    seq_b = [f"{op.direction}:{op.operand_type}" for op in b.operations]

    dist = _levenshtein_distance(seq_a, seq_b)
    max_len = max(len(seq_a), len(seq_b))
    return 1.0 - dist / max_len


def compare_op_histograms(a: OpHistogram, b: OpHistogram) -> float:
    """Compare two operation histograms using cosine similarity."""
    return _cosine_similarity(a.counts, b.counts)


def compare_cfg_shapes(a: CFGShape, b: CFGShape) -> float:
    """Compare two CFG shapes using weighted ratio + cosine similarity."""
    # If both are trivial (0 nodes), they're identical.
    if a.num_nodes == 0 and b.num_nodes == 0:
        return 1.0

    node_sim = _ratio_similarity(a.num_nodes, b.num_nodes)
    edge_sim = _ratio_similarity(a.num_edges, b.num_edges)
    back_edge_sim = _ratio_similarity(a.num_back_edges, b.num_back_edges)
    depth_sim = _ratio_similarity(a.max_loop_depth, b.max_loop_depth)
    degree_sim = _sequence_cosine(a.node_degree_sequence,
                                  b.node_degree_sequence)

    # Weighted combination.
    return (0.25 * node_sim +
            0.25 * edge_sim +
            0.15 * back_edge_sim +
            0.15 * depth_sim +
            0.20 * degree_sim)


def compare_computation_dags(a: ComputationDAGFeatures,
                             b: ComputationDAGFeatures) -> float:
    """Compare two computation DAGs using weighted cosine of sub-features."""
    if a.num_nodes == 0 and b.num_nodes == 0:
        return 1.0

    depth_sim = _ratio_similarity(a.depth, b.depth)
    node_sim = _ratio_similarity(a.num_nodes, b.num_nodes)
    width_sim = _sequence_cosine(a.width_sequence, b.width_sequence)
    opcode_sim = _cosine_similarity(a.opcode_counts, b.opcode_counts)
    leaf_sim = _cosine_similarity(a.leaf_type_counts, b.leaf_type_counts)
    root_sim = _ratio_similarity(a.root_count, b.root_count)

    return (0.15 * depth_sim +
            0.15 * node_sim +
            0.15 * width_sim +
            0.25 * opcode_sim +
            0.15 * leaf_sim +
            0.15 * root_sim)


def compare_type_signatures(a: TypeSignature, b: TypeSignature) -> float:
    """Compare two type signatures: 1.0 if identical, 0.0 otherwise."""
    if a.return_type == b.return_type and a.param_types == b.param_types:
        return 1.0
    return 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fingerprint_function(fn: Function) -> FunctionFingerprint:
    """Extract a complete fingerprint from a single function."""
    return FunctionFingerprint(
        function_name=fn.name,
        io_sequence=extract_io_sequence(fn),
        op_histogram=extract_op_histogram(fn),
        cfg_shape=extract_cfg_shape(fn),
        computation_dag=extract_computation_dag(fn),
        type_signature=extract_type_signature(fn),
    )


def fingerprint_module(mod: Module) -> ModuleFingerprint:
    """Extract fingerprints for all defined functions in a module."""
    fps: dict[str, FunctionFingerprint] = {}
    for fn in mod.functions:
        fps[fn.name] = fingerprint_function(fn)
    return ModuleFingerprint(function_fingerprints=fps)


def compare_fingerprints(
    a: FunctionFingerprint,
    b: FunctionFingerprint,
    weights: Optional[dict[str, float]] = None,
) -> tuple[float, FeatureScores]:
    """Compare two function fingerprints and return (score, feature_scores)."""
    w = weights if weights is not None else DEFAULT_WEIGHTS

    scores = FeatureScores(
        io_sequence=compare_io_sequences(a.io_sequence, b.io_sequence),
        computation_dag=compare_computation_dags(
            a.computation_dag, b.computation_dag
        ),
        cfg_shape=compare_cfg_shapes(a.cfg_shape, b.cfg_shape),
        op_histogram=compare_op_histograms(a.op_histogram, b.op_histogram),
        type_signature=compare_type_signatures(
            a.type_signature, b.type_signature
        ),
    )

    overall = (
        w.get("io_sequence", 0.0) * scores.io_sequence
        + w.get("computation_dag", 0.0) * scores.computation_dag
        + w.get("cfg_shape", 0.0) * scores.cfg_shape
        + w.get("op_histogram", 0.0) * scores.op_histogram
        + w.get("type_signature", 0.0) * scores.type_signature
    )

    return overall, scores


def compare_module_fingerprints(
    a: ModuleFingerprint,
    b: ModuleFingerprint,
    weights: Optional[dict[str, float]] = None,
) -> FingerprintResult:
    """Compare two module fingerprints."""
    names_a = set(a.function_fingerprints.keys())
    names_b = set(b.function_fingerprints.keys())

    matched = sorted(names_a & names_b)
    unmatched_a = sorted(names_a - names_b)
    unmatched_b = sorted(names_b - names_a)

    if not matched:
        return FingerprintResult(
            overall_score=0.0,
            feature_scores=FeatureScores(),
            weights=weights if weights is not None else dict(DEFAULT_WEIGHTS),
            matched_functions=matched,
            unmatched_a=unmatched_a,
            unmatched_b=unmatched_b,
        )

    # Average scores across matched functions.
    total_io = 0.0
    total_dag = 0.0
    total_cfg = 0.0
    total_op = 0.0
    total_type = 0.0
    total_overall = 0.0

    for name in matched:
        fp_a = a.function_fingerprints[name]
        fp_b = b.function_fingerprints[name]
        score, fs = compare_fingerprints(fp_a, fp_b, weights)
        total_overall += score
        total_io += fs.io_sequence
        total_dag += fs.computation_dag
        total_cfg += fs.cfg_shape
        total_op += fs.op_histogram
        total_type += fs.type_signature

    n = len(matched)
    avg_scores = FeatureScores(
        io_sequence=total_io / n,
        computation_dag=total_dag / n,
        cfg_shape=total_cfg / n,
        op_histogram=total_op / n,
        type_signature=total_type / n,
    )

    # Penalize for unmatched functions.
    total_functions = len(names_a | names_b)
    match_ratio = n / total_functions if total_functions > 0 else 1.0
    overall = (total_overall / n) * match_ratio

    return FingerprintResult(
        overall_score=overall,
        feature_scores=avg_scores,
        weights=weights if weights is not None else dict(DEFAULT_WEIGHTS),
        matched_functions=matched,
        unmatched_a=unmatched_a,
        unmatched_b=unmatched_b,
    )


def compare_modules_fingerprint(
    mod_a: Module,
    mod_b: Module,
    weights: Optional[dict[str, float]] = None,
) -> FingerprintResult:
    """Convenience: fingerprint two modules and compare them."""
    fp_a = fingerprint_module(mod_a)
    fp_b = fingerprint_module(mod_b)
    return compare_module_fingerprints(fp_a, fp_b, weights)


def fingerprint_cpp_files(
    file_a: str | Path,
    file_b: str | Path,
    weights: Optional[dict[str, float]] = None,
    clang_path: Optional[str | Path] = None,
    opt_path: Optional[str | Path] = None,
) -> FingerprintResult:
    """End-to-end: compile two C++ files and compare their fingerprints."""
    from semantic_equiv.normalize import normalize_cpp

    file_a = Path(file_a)
    file_b = Path(file_b)

    with tempfile.TemporaryDirectory(prefix="semantic_fp_") as tmpdir:
        norm_a = normalize_cpp(file_a, output_dir=Path(tmpdir) / "a",
                               clang_path=clang_path, opt_path=opt_path)
        norm_b = normalize_cpp(file_b, output_dir=Path(tmpdir) / "b",
                               clang_path=clang_path, opt_path=opt_path)

        mod_a = parse_llvm_ir(norm_a)
        mod_b = parse_llvm_ir(norm_b)

    return compare_modules_fingerprint(mod_a, mod_b, weights)
