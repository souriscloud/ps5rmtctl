"""Button name resolution.

Maps the friendly names the user cares about onto the canonical button names
that :class:`pyremoteplay.controller.Controller` understands.

Canonical buttons (from ``Controller.buttons()``)::

    UP DOWN LEFT RIGHT L1 R1 L2 R2 CROSS CIRCLE SQUARE TRIANGLE
    OPTIONS SHARE PS L3 R3 TOUCHPAD
"""
from __future__ import annotations

from typing import List

# Canonical names exposed by the DualSense feedback protocol.
CANONICAL: List[str] = [
    "UP", "DOWN", "LEFT", "RIGHT",
    "L1", "R1", "L2", "R2", "L3", "R3",
    "CROSS", "CIRCLE", "SQUARE", "TRIANGLE",
    "OPTIONS", "SHARE", "PS", "TOUCHPAD",
]

# Friendly aliases -> canonical. The originally requested control set is:
#   left, right, up, down, home, pause, option, cross, square, triangle,
#   circle, l1, l2, r1, r2
# Note: per project decision, both "pause" and "option" map to OPTIONS, and
# "home" maps to PS. The DualSense has no dedicated pause button.
ALIASES = {
    # d-pad
    "up": "UP", "down": "DOWN", "left": "LEFT", "right": "RIGHT",
    # face buttons (+ common shorthands)
    "cross": "CROSS", "x": "CROSS",
    "circle": "CIRCLE", "o": "CIRCLE",
    "square": "SQUARE",
    "triangle": "TRIANGLE",
    # shoulders / triggers
    "l1": "L1", "l2": "L2", "r1": "R1", "r2": "R2", "l3": "L3", "r3": "R3",
    # system
    "home": "PS", "ps": "PS",
    "option": "OPTIONS", "options": "OPTIONS", "pause": "OPTIONS",
    "share": "SHARE", "create": "SHARE",
    "touchpad": "TOUCHPAD",
}


class UnknownButton(ValueError):
    """Raised when a button name cannot be resolved."""


def resolve(name: str) -> str:
    """Return the canonical button name for ``name`` (case-insensitive).

    Accepts both friendly aliases (``home``, ``pause``, ``x``) and canonical
    names (``PS``, ``CROSS``).
    """
    if not isinstance(name, str) or not name.strip():
        raise UnknownButton(f"Invalid button: {name!r}")
    key = name.strip().lower()
    if key in ALIASES:
        return ALIASES[key]
    upper = name.strip().upper()
    if upper in CANONICAL:
        return upper
    raise UnknownButton(
        f"Unknown button: {name!r}. Valid names: "
        + ", ".join(sorted(ALIASES)) + " (or canonical: " + ", ".join(CANONICAL) + ")"
    )
