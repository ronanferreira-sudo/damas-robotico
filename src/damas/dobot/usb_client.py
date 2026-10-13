import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .constants import HOME_X, HOME_Y, HOME_Z, HOME_R, PTP_MOVJ, PTP_MOVL, PTP_MODES
from .exceptions import ConnectionError, RPCError, TimeoutError

logger = logging.getLogger(__name__)

try:
    from pydobot import Dobot as Pydobot
    from pydobot.enums import PTPMode as _PTPMode
    _PYDOBOT_AVAILABLE = True
except ImportError:
    _PYDOBOT_AVAILABLE = False
    Pydobot = None
    _PTPMode = None


def _to_ptp_mode(mode_int: int):
    """Converte inteiro para o enum PTPMode que o pydobot exige."""
    if _PTPMode is not None:
        try:
            return _PTPMode(mode_int)
        except ValueError:
            pass
    return mode_int



class USBClient:
    """Cliente USB direto usando pydobot como backend."""

    def __init__(self, port: str = "auto", baudrate: int = 115200, timeout: float = 1.0, max_retries: int = 3):
        if not _PYDOBOT_AVAILABLE:
            raise ImportError(
                "pydobot is not installed. "
                "Install it with: pip install pydobot"
            )
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.max_retries = max_retries
        self._robo = None
        self._executor = ThreadPoolExecutor(max_workers=1)
        self._lock = asyncio.Lock()

    @staticmethod
    def find_port() -> str | None:
        import serial.tools.list_ports
        ports = serial.tools.list_ports.comports()
        for p in ports:
            desc = (p.description or "").lower()
            if "dobot" in desc or "usb serial" in desc or "ch340" in desc:
                return p.device
        for p in ports:
            if "com" in p.device.lower() or "ttyusb" in p.device.lower() or "ttyacm" in p.device.lower():
                return p.device
        return None

    async def connect(self) -> None:
        if self.port == "auto" or not self.port:
            self.port = self.find_port()
            if not self.port:
                raise ConnectionError("Nenhuma porta serial compativel encontrada")
            logger.info(f"Porta auto-detectada: {self.port}")

        logger.info(f"Connecting via USB on {self.port}")
        try:
            await asyncio.get_event_loop().run_in_executor(self._executor, self._do_connect)
            logger.info("USB connected")
        except Exception as exc:
            raise ConnectionError(f"Failed to connect via USB: {exc}") from exc

    def _do_connect(self) -> None:
        self._robo = Pydobot(port=self.port)
        logger.info("pydobot initialized")

    async def disconnect(self) -> None:
        if self._robo is not None:
            try:
                await asyncio.get_event_loop().run_in_executor(self._executor, self._robo.close)
            except Exception as exc:
                logger.warning(f"Error disconnecting USB: {exc}")
            finally:
                self._robo = None
        self._executor.shutdown(wait=False)

    @property
    def connected(self) -> bool:
        return self._robo is not None

    async def send(self, method: str, params: dict[str, Any] | None = None) -> Any:
        if not self.connected:
            raise ConnectionError("USB not connected")

        if params is None:
            params = {}

        async with self._lock:
            for attempt in range(1, self.max_retries + 1):
                try:
                    return await asyncio.get_event_loop().run_in_executor(
                        self._executor,
                        self._do_send,
                        method,
                        params,
                    )
                except Exception as exc:
                    if attempt == self.max_retries:
                        raise ConnectionError(f"USB command failed: {exc}") from exc
                    logger.warning(f"Attempt {attempt} failed: {exc}")

        raise ConnectionError("Max retries exceeded for USB command")

    async def command(self, method: str, **params: Any) -> Any:
        return await self.send(method, params)

    def _do_send(self, method: str, params: dict[str, Any]) -> Any:
        robo = self._robo

        if method == "set_homecmd":
            robo._set_ptp_cmd(HOME_X, HOME_Y, HOME_Z, HOME_R,
                              mode=_to_ptp_mode(PTP_MODES["MOVJ_XYZ"]), wait=True)
            return None
        elif method == "set_ptpcmd":
            mode = _to_ptp_mode(int(params.get("ptp_mode", PTP_MOVJ)))
            robo._set_ptp_cmd(
                x=params.get("x", 0),
                y=params.get("y", 0),
                z=params.get("z", 0),
                r=params.get("r", 0),
                mode=mode,
                wait=True,
            )
            return None

        elif method == "SetQueuedCmdStartExec":
            return None
        elif method == "SetQueuedCmdStopExec":
            return None
        elif method == "SetQueuedCmdClear":
            return None
        elif method == "GetQueuedCmdCurrentIndex":
            return None
        elif method == "SetEndEffectorSuctionCup":
            robo.suck(params.get("on", True))
            return None
        elif method == "SetEndEffectorGripper":
            robo.grip(params.get("on", True))
            return None
        elif method == "SetEndEffectorLaser":
            return None
        elif method == "SetDO":
            robo.set_eio(params.get("index", 0), params.get("status", 0))
            return None
        elif method == "SetPWM":
            return None
        elif method == "GetDI":
            return robo.get_eio(params.get("index", 0))
        elif method == "GetAI":
            return None
        elif method == "GetPose":
            return list(robo.pose())
        elif method == "GetErrorID":
            return None
        elif method == "GetDeviceVersion":
            return None
        elif method == "SetWAITCmd":
            robo.wait(params.get("waitTime", 1000))
            return None
        elif method == "SetCPParams":
            robo.speed(params.get("planVel", 100))
            return None
        elif method == "SetCPCmd":
            robo.move_to(
                x=params.get("x", 0),
                y=params.get("y", 0),
                z=params.get("z", 0),
                r=params.get("r", 0),
            )
            return None
        else:
            raise RPCError(-1, f"Unknown command: {method}")
