import logging
from typing import Any

from .rpc import RPCClient

logger = logging.getLogger(__name__)


class DobotClient:
    """Wrapper que delega comandos para o RPCClient."""

    def __init__(self, host: str = "127.0.0.1", port: int = 9090, max_retries: int = 3):
        self.rpc = RPCClient(host, port, max_retries=max_retries)

    async def connect(self) -> None:
        """Estabelece conexão com o servidor RPC."""
        logger.info("Connecting to Dobot RPC server")
        await self.rpc.connect()

    async def disconnect(self) -> None:
        """Fecha a conexão com o servidor RPC."""
        logger.info("Disconnecting from Dobot RPC server")
        await self.rpc.disconnect()

    async def command(self, method: str, **params: Any) -> Any:
        """Envia um comando RPC e retorna o resultado.

        Args:
            method: Nome do método RPC.
            **params: Parâmetros do comando.

        Returns:
            Resultado retornado pelo servidor.
        """
        logger.debug(f"Sending command: {method}")
        return await self.rpc.send(method, params)
