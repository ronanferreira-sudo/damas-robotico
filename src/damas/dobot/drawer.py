import asyncio
import logging
from typing import Any

from .canvas import Canvas

logger = logging.getLogger(__name__)


class Drawer:
    """Converte caminhos SVG em comandos de desenho contínuo."""

    def __init__(self, canvas: Canvas):
        self.canvas = canvas

    @staticmethod
    def _mm(value: float) -> float:
        return value / 25.4

    @staticmethod
    def _points_to_mm(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
        return [(x / 25.4, y / 25.4) for x, y in points]

    async def draw_points(self, points: list[tuple[float, float]], z: float = 0, absolute: bool = True) -> None:
        """Desenha uma sequência de pontos como linha contínua.

        Args:
            points: Lista de tuplas (x, y) em milímetros.
            z: Altura Z fixa durante o traço.
            absolute: True para coordenadas absolutas.
        """
        if not self.canvas.active:
            raise RuntimeError("Canvas is not active. Call start() first.")

        points_mm = self._points_to_mm(points)
        logger.info(f"Drawing {len(points_mm)} points")

        for x, y in points_mm:
            await self.canvas.line(x, y, z, absolute=absolute)

    async def draw_square(self, x: float, y: float, size: float, z: float = 0) -> None:
        """Desenha um quadrado no plano XY.

        Args:
            x: Canto inferior esquerdo X em mm.
            y: Canto inferior esquerdo Y em mm.
            size: Tamanho do lado em mm.
            z: Altura Z do traço.
        """
        logger.info(f"Drawing square at ({x}, {y}) size={size}")
        points = [
            (x, y),
            (x + size, y),
            (x + size, y + size),
            (x, y + size),
            (x, y),
        ]
        await self.draw_points(points, z=z, absolute=True)

    async def draw_circle(self, cx: float, cy: float, radius: float, segments: int = 36, z: float = 0) -> None:
        """Desenha um círculo aproximado por segmentos.

        Args:
            cx: Centro X em mm.
            cy: Centro Y em mm.
            radius: Raio em mm.
            segments: Quantidade de segmentos da aproximação.
            z: Altura Z do traço.
        """
        logger.info(f"Drawing circle at ({cx}, {cy}) radius={radius}")
        points = []
        for i in range(segments + 1):
            angle = 2 * 3.14159265 * i / segments
            x = cx + radius * __import__('math').cos(angle)
            y = cy + radius * __import__('math').sin(angle)
            points.append((x, y))
        await self.draw_points(points, z=z, absolute=True)
