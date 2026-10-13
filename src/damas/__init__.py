"""damas: jogo contra IA com suporte a bracos Dobot e visao."""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = ["BoardState", "choose_move", "Match", "Calibration", "VisionSystem"]

_EXPORTS = {
    "BoardState": (".draughts", "BoardState"),
    "choose_move": (".draughts", "choose_move"),
    "Match": (".game", "Match"),
    "Calibration": (".vision.calibration", "Calibration"),
    "VisionSystem": (".vision.detector", "VisionSystem"),
}


def __getattr__(name: str) -> Any:
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute = target
    value = getattr(import_module(module_name, __name__), attribute)
    globals()[name] = value
    return value
