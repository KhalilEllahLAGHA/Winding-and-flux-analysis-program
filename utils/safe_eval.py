"""Safe arithmetic evaluation of user-entered text.

The parameter fields accept small expressions such as "41.25+1" or "36*2".
The previous implementation used the built-in ``eval`` which executes
arbitrary code; this module evaluates only literal arithmetic via the AST.
"""

import ast
import operator

_BINARY_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_UNARY_OPERATORS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def safe_eval_arithmetic(expression):
    """Evaluate a numeric arithmetic expression and return a float.

    Raises ValueError for anything other than numbers combined with
    + - * / // % ** and parentheses.
    """
    try:
        tree = ast.parse(expression.strip(), mode='eval')
        return float(_evaluate_node(tree.body))
    except ValueError:
        raise
    except Exception as error:
        raise ValueError(f"Invalid arithmetic expression: {expression!r}") from error


def _evaluate_node(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATORS:
        return _BINARY_OPERATORS[type(node.op)](
            _evaluate_node(node.left), _evaluate_node(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPERATORS:
        return _UNARY_OPERATORS[type(node.op)](_evaluate_node(node.operand))
    raise ValueError(f"Unsupported expression element: {ast.dump(node)}")


def parse_float_field(text, fallback=0.0):
    """Parse a text-field value as float, allowing simple arithmetic.

    Returns ``fallback`` when the field is empty or invalid, mirroring the
    forgiving behaviour the input forms rely on while typing.
    """
    text = (text or '').strip()
    if not text:
        return fallback
    try:
        return safe_eval_arithmetic(text)
    except ValueError:
        return fallback


def parse_int_field(text, fallback=0):
    """Parse a text-field value as int; returns ``fallback`` when invalid."""
    text = (text or '').strip()
    if not text:
        return fallback
    try:
        return int(text)
    except ValueError:
        return fallback
