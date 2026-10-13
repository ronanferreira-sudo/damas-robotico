import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


class Queue:
    """Controle da fila de comandos do robô."""

    def __init__(self, robot: Any) -> None:
        self.robot = robot

    async def start(self) -> Any:
        """Inicia a execução da fila de comandos."""
        logger.info("Starting queue execution")
        return await self.robot.command("SetQueuedCmdStartExec")

    async def stop(self) -> Any:
        """Para a execução da fila de comandos."""
        logger.info("Stopping queue execution")
        return await self.robot.command("SetQueuedCmdStopExec")

    async def clear(self) -> Any:
        """Limpa todos os comandos da fila."""
        logger.info("Clearing command queue")
        return await self.robot.command("SetQueuedCmdClear")

    async def index(self) -> int:
        """Retorna o índice do comando atualmente em execução na fila.

        Returns:
            Índice atual do comando em execução.
        """
        return await self.robot.command("GetQueuedCmdCurrentIndex")

    async def wait_for_queue(self, timeout: int = 60) -> None:
        """Aguarda até que todos os comandos da fila sejam executados.

        Args:
            timeout: Tempo máximo de espera em segundos.

        Raises:
            TimeoutError: Se a fila não terminar dentro do tempo limite.
        """
        logger.info(f"Waiting for queue to finish (timeout={timeout}s)")
        start_time = asyncio.get_event_loop().time()
        while True:
            current_index = await self.index()
            if current_index == -1:
                logger.info("Queue finished")
                break
            if asyncio.get_event_loop().time() - start_time > timeout:
                raise TimeoutError(
                    f"Queue did not finish within {timeout} seconds"
                )
            await asyncio.sleep(0.1)
