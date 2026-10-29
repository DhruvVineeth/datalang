"""One conservative IR optimization: guarded double-NOT elimination.

The original instructions and predicate structure remain available for diagnostics
and IR display. Only an execution hint is added, on a separate copy of the IR.
"""

from copy import copy
from dataclasses import replace

from src.interpreter.ir import BoolPred, ComparePred, FilterIR, IRProgram, NotPred


def optimize_ir(program: IRProgram, *, enabled: bool = True) -> IRProgram:
    """Annotate eligible FILTER predicates after semantic validation and lowering."""
    if not enabled:
        return program
    instructions = []
    for instruction in program.instructions:
        if type(instruction) is FilterIR and instruction.condition is not None:
            condition = _annotate(instruction.condition)
            if condition is not instruction.condition:
                instruction = copy(instruction)
                instruction.condition = condition
        instructions.append(instruction)
    return IRProgram(instructions)


def _annotate(root):
    # Iterative traversal adds no recursion limit below the existing compiler's.
    # Leave unknown/malformed/custom or shared/cyclic predicate graphs alone.
    pending, order, seen = [root], [], set()
    while pending:
        node = pending.pop()
        if id(node) in seen:
            return root
        seen.add(id(node))
        order.append(node)
        if type(node) is ComparePred:
            if node.op not in ("EQ", "NEQ", "LT", "GT", "LE", "GE"):
                return root
        elif type(node) is NotPred:
            pending.append(node.operand)
        elif type(node) is BoolPred and node.op in ("AND", "OR"):
            pending.extend((node.left, node.right))
        else:
            return root
    if not any(type(node) is NotPred and type(node.operand) is NotPred for node in order):
        return root
    copies = {}
    for node in reversed(order):
        if type(node) is ComparePred:
            result = replace(node)
        elif type(node) is NotPred:
            result = replace(
                node, operand=copies[id(node.operand)],
                elide_double_not=type(node.operand) is NotPred,
            )
        else:
            result = replace(node, left=copies[id(node.left)], right=copies[id(node.right)])
        copies[id(node)] = result
    return copies[id(root)]
