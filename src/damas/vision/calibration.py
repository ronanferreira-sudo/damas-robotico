"""Calibracao da visao: mapeia quadrados do tabuleiro para pixels da imagem."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import yaml


@dataclass
class Calibration:
    """Mapeamento dos quadrados para coordenadas de pixels [u, v]."""

    square_centers: dict[str, list[float]] = field(default_factory=dict)
    roi_size: int = 48
    empty_reference: str | None = None

    def center(self, square: str) -> tuple[float, float]:
        c = self.square_centers.get(square)
        if c is None:
            raise KeyError(f"Quadrado {square} nao calibrado.")
        return float(c[0]), float(c[1])

    def save(self, path: str) -> None:
        data: dict[str, Any] = {
            "camera": {
                "square_centers": self.square_centers,
                "roi_size": self.roi_size,
                "empty_reference": self.empty_reference,
            }
        }
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
        print(f"Calibracao salva em {path}")

    @classmethod
    def load(cls, path: str) -> "Calibration":
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        cam = data.get("camera", {})
        return cls(
            square_centers={k: list(v) for k, v in (cam.get("square_centers") or {}).items()},
            roi_size=int(cam.get("roi_size", 48)),
            empty_reference=cam.get("empty_reference"),
        )

    @classmethod
    def build_from_corners(
        cls,
        a1: tuple[float, float],
        a8: tuple[float, float],
        h1: tuple[float, float],
        h8: tuple[float, float],
        roi_size: int = 48,
    ) -> "Calibration":
        """Interpola os centros a partir dos 4 cantos do tabuleiro."""
        centers: dict[str, list[float]] = {}
        for rank in range(1, 9):
            t = (rank - 1) / 7.0
            for file_idx in range(8):
                s = file_idx / 7.0
                f = chr(ord("a") + file_idx)
                sq = f"{f}{rank}"
                u = (1 - s) * ((1 - t) * a1[0] + t * a8[0]) + s * ((1 - t) * h1[0] + t * h8[0])
                v = (1 - s) * ((1 - t) * a1[1] + t * a8[1]) + s * ((1 - t) * h1[1] + t * h8[1])
                centers[sq] = [round(u, 1), round(v, 1)]
        return cls(square_centers=centers, roi_size=roi_size)


def all_squares() -> list[str]:
    # a1 to h8
    out = []
    for rank in range(1, 9):
        for file_idx in range(8):
            f = chr(ord("a") + file_idx)
            out.append(f"{f}{rank}")
    return out
