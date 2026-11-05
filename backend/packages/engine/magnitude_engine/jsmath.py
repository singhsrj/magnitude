"""JavaScript-compatible numeric helpers (so Python reproduces what the TS engine computes)."""
from __future__ import annotations

import math


def js_round(x: float) -> int:
    """Math.round: halves round toward +infinity (Python's round() uses banker's rounding)."""
    f = math.floor(x)
    return f + 1 if x - f >= 0.5 else f


def base36(n: int) -> str:
    """Number.prototype.toString(36) for non-negative integers."""
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    if n == 0:
        return "0"
    out = []
    while n:
        n, r = divmod(n, 36)
        out.append(digits[r])
    return "".join(reversed(out))


def clamp(n: float, lo: float, hi: float) -> float:
    return min(hi, max(lo, n))
