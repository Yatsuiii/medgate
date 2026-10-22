"""The agent's calculator: arithmetic and date differences over an allowlist, evaluated by walking the syntax tree.

There is no eval and no attribute access, so an expression can only reach the operators and functions listed here.
Operands of arithmetic must be numbers, and every result is bounded, so no expression can build a huge value.
"""

import ast
import math
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

MAX_EXPRESSION_CHARS = 500
MAX_EXPONENT = 100
MAX_MAGNITUDE = 1e12  # far beyond any dose, count or average, and small enough that powers stay cheap


class CalculatorError(ValueError):
    pass


def _moment(text: str) -> datetime:
    """An ISO date or date-time; one without a time zone is taken as UTC, the zone the benchmark's records use."""
    moment = datetime.fromisoformat(text)
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def _hours_between(start: str, end: str) -> float:
    return (_moment(end) - _moment(start)).total_seconds() / 3600


def _days_between(start: str, end: str) -> float:
    return _hours_between(start, end) / 24


def _years_between(start: str, end: str) -> int:
    """Completed years from start to end, for example an age on a given day."""
    a, b = _moment(start), _moment(end)
    return b.year - a.year - ((b.month, b.day) < (a.month, a.day))


FUNCTIONS: dict[str, Callable[..., Any]] = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sum": sum,
    "len": len,
    "floor": math.floor,
    "ceil": math.ceil,
    "sqrt": math.sqrt,
    "hours_between": _hours_between,
    "days_between": _days_between,
    "years_between": _years_between,
}
_BINARY: dict[type[ast.operator], Callable[[Any, Any], Any]] = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.FloorDiv: lambda a, b: a // b,
    ast.Mod: lambda a, b: a % b,
    ast.Pow: lambda a, b: a**b,
}
_UNARY: dict[type[ast.unaryop], Callable[[Any], Any]] = {ast.USub: lambda a: -a, ast.UAdd: lambda a: +a}


def evaluate(expression: str) -> Any:
    """The value of `expression`: a number, a string or a list. Raises CalculatorError with a readable reason."""
    if len(expression) > MAX_EXPRESSION_CHARS:
        raise CalculatorError(f"expression longer than {MAX_EXPRESSION_CHARS} characters")
    try:
        tree = ast.parse(expression.strip(), mode="eval")
    except SyntaxError as exc:
        raise CalculatorError(f"not a valid expression: {exc.msg}") from None
    except (RecursionError, MemoryError):
        raise CalculatorError("expression nested too deeply") from None
    try:
        return _value(tree.body)
    except CalculatorError:
        raise
    except RecursionError:
        raise CalculatorError("expression nested too deeply") from None
    except (ArithmeticError, ValueError, TypeError) as exc:
        raise CalculatorError(str(exc)) from None


def _number(value: Any) -> float | int:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise CalculatorError(f"arithmetic needs numbers, got {value!r}")
    return value


def _bounded(value: Any) -> Any:
    if isinstance(value, int | float) and not isinstance(value, bool) and abs(value) > MAX_MAGNITUDE:
        raise CalculatorError("result too large")
    return value


def _value(node: ast.expr) -> Any:
    match node:
        case ast.Constant(value=bool()):
            raise CalculatorError("booleans are not supported")
        case ast.Constant(value=int() | float() | str() as value):
            return value
        case ast.List(elts=items) | ast.Tuple(elts=items):
            return [_value(item) for item in items]
        case ast.UnaryOp(op=op, operand=operand) if type(op) in _UNARY:
            return _UNARY[type(op)](_number(_value(operand)))
        case ast.BinOp(left=left, op=op, right=right) if type(op) in _BINARY:
            a, b = _number(_value(left)), _number(_value(right))
            if isinstance(op, ast.Pow) and abs(b) > MAX_EXPONENT:
                raise CalculatorError(f"exponent larger than {MAX_EXPONENT}")
            return _bounded(_BINARY[type(op)](a, b))
        case ast.Call(func=ast.Name(id=name), args=args, keywords=[]) if name in FUNCTIONS:
            return _bounded(FUNCTIONS[name](*(_value(arg) for arg in args)))
        case _:
            raise CalculatorError(f"not allowed: {ast.unparse(node)}")
