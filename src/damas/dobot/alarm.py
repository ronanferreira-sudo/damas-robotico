import warnings
from typing import Any

warnings.warn(
    "dobot.alarm está depreciado. Use dobot.dashboard.get_alarm() e dobot.dashboard.clear_error().",
    DeprecationWarning,
    stacklevel=2
)


class Alarm:

    def __init__(self, robot: Any) -> None:
        self.robot = robot

    async def clear(self) -> Any:
        return await self.robot.command("ClearError")

    async def get(self) -> Any:
        return await self.robot.command("GetErrorID")
