import logging
from typing import Any

logger = logging.getLogger(__name__)


class Dashboard:
    """Comandos de sistema e diagnóstico do robô."""

    def __init__(self, robot: Any) -> None:
        self.robot = robot

    async def clear_error(self) -> Any:
        """Limpa erros/alarmes ativos do robô."""
        logger.info("Clearing errors")
        return await self.robot.command("ClearError")

    async def get_alarm(self) -> Any:
        """Retorna o ID do erro/alarme atual."""
        logger.debug("Getting alarm ID")
        return await self.robot.command("GetErrorID")

    async def get_pose(self) -> Any:
        """Retorna a pose atual do robô (posição e orientação)."""
        logger.debug("Getting current pose")
        return await self.robot.command("GetPose")

    async def get_version(self) -> Any:
        """Retorna a versão do firmware/dispositivo."""
        logger.debug("Getting device version")
        return await self.robot.command("GetDeviceVersion")

    async def wait(self, ms: int) -> Any:
        """Aguarda um tempo em milissegundos.

        Args:
            ms: Tempo de espera em milissegundos.
        """
        logger.debug(f"Waiting {ms}ms")
        return await self.robot.command(
            "SetWAITCmd",
            waitTime=ms
        )
