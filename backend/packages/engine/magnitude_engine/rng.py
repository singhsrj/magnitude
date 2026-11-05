"""Seedable PRNG, bit-for-bit identical to mulberry32 in lib/engine/rng.ts.

Same seed -> same sequence in TypeScript and Python. The parity tests depend on it.
"""
from __future__ import annotations

from typing import Callable, Sequence, TypeVar

Rng = Callable[[], float]
T = TypeVar("T")

_M = 0xFFFFFFFF


def mulberry32(seed: int) -> Rng:
    a = seed & _M

    def rng() -> float:
        nonlocal a
        a = (a + 0x6D2B79F5) & _M
        t = a
        t = ((t ^ (t >> 15)) * (t | 1)) & _M
        t = t ^ ((t + (((t ^ (t >> 7)) * (t | 61)) & _M)) & _M)
        return ((t ^ (t >> 14)) & _M) / 4294967296

    return rng


def rand_int(rng: Rng, lo: int, hi: int) -> int:
    """Inclusive on both ends, like randInt in the TS engine."""
    return int(rng() * (hi - lo + 1)) + lo


def pick(rng: Rng, items: Sequence[T]) -> T:
    return items[int(rng() * len(items))]
