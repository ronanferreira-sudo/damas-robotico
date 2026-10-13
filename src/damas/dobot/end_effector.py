import logging
from typing import Any

logger = logging.getLogger(__name__)


class EndEffector:
    """Controle dos end-effectors (ferramentas) do robô."""

    def __init__(self, robot: Any) -> None:
        self.robot = robot

    async def suction(self, enable: bool = True) -> Any:
        """Liga ou desliga a ventosa de sucção.

        Args:
            enable: True para ligar, False para desligar.
        """
        logger.info(f"Suction {'ON' if enable else 'OFF'}")
        return await self.robot.command(
            "SetEndEffectorSuctionCup",
            enableCtrl=True,
            on=enable
        )

    async def gripper(self, enable: bool = True) -> Any:
        """Abre ou fecha a garra.

        Args:
            enable: True para fechar, False para abrir.
        """
        logger.info(f"Gripper {'CLOSE' if enable else 'OPEN'}")
        return await self.robot.command(
            "SetEndEffectorGripper",
            enableCtrl=True,
            on=enable
        )

    async def laser(self, enable: bool = True) -> Any:
        """Liga ou desliga o laser.

        Args:
            enable: True para ligar, False para desligar.
        """
        logger.info(f"Laser {'ON' if enable else 'OFF'}")
        return await self.robot.command(
            "SetEndEffectorLaser",
            enableCtrl=True,
            on=enable
        )
