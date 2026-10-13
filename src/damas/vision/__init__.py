"""Pacote de visao computacional com importacoes opcionais sob demanda."""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = ["Calibration", "Camera", "BoardDetector", "VisionSystem"]

_MODULES = {
    "Calibration": ".calibration",
    "Camera": ".camera",
    "BoardDetector": ".detector",
    "VisionSystem": ".detector",
}


def __getattr__(name: str) -> Any:
    module_name = _MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name, __name__), name)
    globals()[name] = value
    return value
