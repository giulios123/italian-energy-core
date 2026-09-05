"""Common constrained types and Decimal parsing helpers."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Annotated, Any

from pydantic import StringConstraints

BandCode = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=32,
        pattern=r"^[A-Za-z0-9_.:-]+$",
    ),
]


def strict_decimal(value: Any) -> Decimal:
    """Parse a finite Decimal while explicitly rejecting binary floats."""

    if isinstance(value, (bool, float)):
        raise TypeError("economic values must not be bool or float")
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, (str, int)):
        try:
            result = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError("invalid decimal value") from exc
    else:
        raise TypeError("economic values must be Decimal, int, or decimal string")
    if not result.is_finite():
        raise ValueError("economic values must be finite")
    return result
