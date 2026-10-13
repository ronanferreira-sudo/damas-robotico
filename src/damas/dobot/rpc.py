import asyncio
import json
import logging
from typing import Any

import websockets

from .exceptions import ConnectionError as DobotConnectionError
from .exceptions import TimeoutError as DobotTimeoutError
from .utils import parse_result

logger = logging.getLogger(__name__)


class RPCClient:
    """Cliente JSON-RPC 2.0 sobre WebSocket para comunicação com o Dobot."""

    def __init__(self, host: str = "127.0.0.1", port: int = 9090, timeout: int = 10, max_retries: int = 3):
        self.host = host
        self.port = port
        self.ws = None
        self.id = 0
        self.timeout = timeout
        self.max_retries = max_retries
        self._was_connected = False

    async def connect(self) -> None:
        """Estabelece conexão WebSocket com o servidor RPC."""
        logger.info(f"Connecting to {self.host}:{self.port}")
        self.ws = await websockets.connect(
            f"ws://{self.host}:{self.port}"
        )
        self._was_connected = True

    async def disconnect(self) -> None:
        """Fecha a conexão WebSocket se estiver aberta."""
        if self.ws is not None:
            try:
                await self.ws.close()
            except Exception:
                pass
            self.ws = None

    @property
    def connected(self) -> bool:
        """Retorna True se a conexao WebSocket estiver ativa."""
        return self.ws is not None

    async def _reconnect(self) -> None:
        """Tenta reconectar com backoff exponencial."""
        for attempt in range(1, self.max_retries + 1):
            wait = min(2 ** attempt, 30)
            logger.warning(f"Connection lost. Attempting reconnect {attempt}/{self.max_retries} in {wait}s...")
            await asyncio.sleep(wait)
            try:
                await self.connect()
                logger.info("Reconnected successfully")
                return
            except Exception as exc:
                logger.error(f"Reconnect attempt {attempt} failed: {exc}")
        raise DobotConnectionError(
            f"Failed to reconnect after {self.max_retries} attempts"
        )

    async def send(self, method: str, params: dict[str, Any] | None = None) -> Any:
        """Envia uma chamada JSON-RPC e retorna o resultado.

        Args:
            method: Nome do método RPC a ser chamado.
            params: Dicionário de parâmetros da chamada.

        Returns:
            O resultado retornado pelo servidor.

        Raises:
            ConnectionError: Se não estiver conectado ou a conexão fechar.
            TimeoutError: Se a resposta exceder o tempo limite.
            RPCError: Se o servidor retornar um erro JSON-RPC.
        """
        if params is None:
            params = {}

        self.id += 1

        payload = {
            "id": self.id,
            "jsonrpc": "2.0",
            "method": method,
            "params": params
        }

        for attempt in range(1, self.max_retries + 1):
            try:
                if not self.connected:
                    if not self._was_connected:
                        raise DobotConnectionError("Not connected to Dobot RPC server")
                    await self._reconnect()

                logger.debug(f"Sending: {method} {params}")
                await self.ws.send(json.dumps(payload))

                try:
                    resposta = await asyncio.wait_for(
                        self.ws.recv(), timeout=self.timeout
                    )
                except TimeoutError:
                    raise DobotTimeoutError(
                        f"RPC call '{method}' timed out after {self.timeout}s"
                    )
                except websockets.ConnectionClosed:
                    logger.warning("Connection closed during recv, will retry...")
                    self.ws = None
                    continue
                except websockets.ConnectionClosedError:
                    logger.warning("Connection closed unexpectedly, will retry...")
                    self.ws = None
                    continue

                result = parse_result(json.loads(resposta))
                logger.debug(f"Received: {result}")
                return result

            except (DobotConnectionError, DobotTimeoutError):
                if attempt == self.max_retries:
                    raise
                logger.warning(f"Attempt {attempt} failed, retrying...")

        raise DobotConnectionError("Max retries exceeded for RPC call")
