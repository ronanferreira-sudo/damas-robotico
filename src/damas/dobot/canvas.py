import asyncio
import logging

from typing import Any

logger = logging.getLogger(__name__)


class Canvas:
    """Desenho contínuo (Continuous Path) para movimentos suaves."""

    def __init__(self, robot):
        self.robot = robot
        self._active = False

    async def start(self, speed: int = 100, acceleration: int = 100) -> Any:
        """Inicia o modo de desenho contínuo (CP).

        Args:
            speed: Velocidade de planejamento (1-2000 mm/s).
            acceleration: Aceleração (1-2000 mm/s²).

        Returns:
            Resultado do comando.
        """
        logger.info(f"Starting continuous path mode (speed={speed}, acceleration={acceleration})")
        await self.robot.command(
            "SetCPParams",
            planVel=speed,
            acc=acceleration,
            dirty=0
        )
        self._active = True
        return await self.robot.command("SetQueuedCmdStartExec")

    async def stop(self) -> Any:
        """Para o modo de desenho contínuo.

        Returns:
            Resultado do comando.
        """
        logger.info("Stopping continuous path mode")
        self._active = False
        return await self.robot.command("SetQueuedCmdStopExec")

    async def line(self, x: float, y: float, z: float, r: float = 0, absolute: bool = True) -> Any:
        """Desenha uma linha no modo contínuo.

        Args:
            x: Posição X em mm.
            y: Posição Y em mm.
            z: Posição Z em mm.
            r: Rotação em graus.
            absolute: True para coordenadas absolutas, False para relativas.

        Returns:
            Resultado do comando.
        """
        if not self._active:
            raise RuntimeError("Canvas is not active. Call start() first.")
        logger.debug(f"CP line to ({x}, {y}, {z}, r={r}) absolute={absolute}")
        return await self.robot.command(
            "SetCPCmd",
            cpMode=1 if absolute else 0,
            x=x,
            y=y,
            z=z,
            r=r
        )

    async def arc(self, x: float, y: float, z: float, r: float = 0, absolute: bool = True) -> Any:
        """Desenha um arco no modo contínuo (se suportado pelo firmware).

        Args:
            x: Posição X em mm.
            y: Posição Y em mm.
            z: Posição Z em mm.
            r: Rotação em graus.
            absolute: True para coordenadas absolutas, False para relativas.

        Returns:
            Resultado do comando.
        """
        if not self._active:
            raise RuntimeError("Canvas is not active. Call start() first.")
        logger.debug(f"CP arc to ({x}, {y}, {z}, r={r}) absolute={absolute}")
        return await self.robot.command(
            "SetCPCmd",
            cpMode=3 if absolute else 2,
            x=x,
            y=y,
            z=z,
            r=r
        )

    @property
    def active(self) -> bool:
        """Retorna True se o modo de desenho contínuo estiver ativo."""
        return self._active
