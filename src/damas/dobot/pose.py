import warnings
from typing import Any

warnings.warn(
    "dobot.pose está depreciado. Use dobot.dashboard.get_pose().",
    DeprecationWarning,
    stacklevel=2
)


class Pose:

    def __init__(self, robot: Any) -> None:
        self.robot = robot

    async def get(self) -> Any:
        return await self.robot.command("GetPose")
