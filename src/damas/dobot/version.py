import warnings
from typing import Any

warnings.warn(
    "dobot.version está depreciado. Use dobot.dashboard.get_version().",
    DeprecationWarning,
    stacklevel=2
)


class Version:

    def __init__(self, robot: Any) -> None:
        self.robot = robot

    async def get(self) -> Any:
        return await self.robot.command("GetDeviceVersion")
