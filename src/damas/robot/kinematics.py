"""Transformada de coordenadas: quadrado do tabuleiro -> coordenada do robo.

Assume uma transformada rigida (translacao + rotacao + escala uniforme) entre
o sistema de referencia do tabuleiro e o do braco. E suficiente para um
tabuleiro plano e alinhado; calibracoes mais complexas podem ser adicionadas
depois (ex.: homografia de 4 pontos).
"""

from __future__ import annotations

import math
from typing import Mapping


class BoardToRobot:
    def __init__(
        self,
        origin_x: float = 0.0,
        origin_y: float = 0.0,
        spacing: float = 45.0,
        rotation_deg: float = 0.0,
        corners: dict[str, dict[str, float]] | None = None,
        square_overrides: dict[str, dict[str, float]] | None = None,
    ) -> None:
        self.corners = corners
        self.square_overrides = square_overrides or {}
        self.origin_x = origin_x
        self.origin_y = origin_y
        self.spacing = spacing
        self.rotation_deg = rotation_deg
        self._cos = math.cos(math.radians(rotation_deg))
        self._sin = math.sin(math.radians(rotation_deg))

    @classmethod
    def from_config(cls, cfg: Mapping) -> "BoardToRobot":
        return cls(
            origin_x=float(cfg.get("origin_x", 0.0)),
            origin_y=float(cfg.get("origin_y", 0.0)),
            spacing=float(cfg.get("spacing", 45.0)),
            rotation_deg=float(cfg.get("rotation_deg", 0.0)),
            corners=cfg.get("corners"),
            square_overrides=cfg.get("square_overrides"),
        )

    def _indices(self, square: str) -> tuple[int, int]:
        file_idx = ord(square[0].lower()) - ord("a")
        rank_idx = int(square[1]) - 1
        if not (0 <= file_idx <= 7 and 0 <= rank_idx <= 7):
            raise ValueError(f"Quadrado invalido: {square}")
        return file_idx, rank_idx

    def to_xy(self, square: str) -> tuple[float, float]:
        """Retorna (x, y) do centro do quadrado no espaco do robo (mm)."""
        x, y, _ = self.to_xyz_interpolated(square, 0.0)
        return x, y

    def to_xyz_interpolated(self, square: str, fallback_z: float) -> tuple[float, float, float]:
        sq_key = square.upper()
        if sq_key in self.square_overrides:
            ov = self.square_overrides[sq_key]
            return float(ov["x"]), float(ov["y"]), float(ov.get("z", fallback_z))

        fx, ry = self._indices(square)
        if self.corners and all(k in self.corners for k in ["A1", "H1", "A8", "H8"]):
            u = fx / 7.0
            v = ry / 7.0
            
            c_a1 = self.corners["A1"]
            c_h1 = self.corners["H1"]
            c_a8 = self.corners["A8"]
            c_h8 = self.corners["H8"]
            
            x = (1 - u)*(1 - v)*c_a1["x"] + u*(1 - v)*c_h1["x"] + (1 - u)*v*c_a8["x"] + u*v*c_h8["x"]
            y = (1 - u)*(1 - v)*c_a1["y"] + u*(1 - v)*c_h1["y"] + (1 - u)*v*c_a8["y"] + u*v*c_h8["y"]
            z = (1 - u)*(1 - v)*c_a1.get("z", fallback_z) + u*(1 - v)*c_h1.get("z", fallback_z) + (1 - u)*v*c_a8.get("z", fallback_z) + u*v*c_h8.get("z", fallback_z)
            return x, y, z
            
        dx = fx * self.spacing
        dy = ry * self.spacing
        x = self.origin_x + dx * self._cos - dy * self._sin
        y = self.origin_y + dx * self._sin + dy * self._cos
        return x, y, fallback_z

    def to_xyz(self, square: str, z: float) -> tuple[float, float, float]:
        """Mantido por compatibilidade, mas idealmente usar to_xyz_interpolated."""
        x, y = self.to_xy(square)
        return x, y, z


def grid_squares(files: int, ranks: int) -> list[str]:
    """Gera os nomes dos quadrados de uma grade ``files`` x ``ranks``.

    Exemplo: ``grid_squares(4, 4)`` retorna ``a1..d4`` (16 quadrados), em
    ordem de rank (a1, b1, c1, d1, a2, ...).
    """
    out: list[str] = []
    for rank in range(1, ranks + 1):
        for file_idx in range(files):
            out.append(f"{chr(ord('a') + file_idx)}{rank}")
    return out
