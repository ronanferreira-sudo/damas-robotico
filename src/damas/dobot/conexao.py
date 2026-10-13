"""
Módulo de conexão com o Dobot Magician Lite.
ATENÇÃO: Este módulo está depreciado. Use a API async em dobot.robot.Robot.
"""

import time
import warnings
from typing import Any

from DobotEDU import m_lite


class Dobot:

    def __init__(self) -> None:
        warnings.warn(
            "dobot.conexao.Dobot está depreciado. Use dobot.Robot com API async.",
            DeprecationWarning,
            stacklevel=2
        )
        self.robo: Any = m_lite

    def home(self) -> None:
        """Executa o Home e aguarda a conclusão."""
        self.robo.set_homecmd()
        time.sleep(5)

    def mover(self, x: Any, y: Any, z: Any, r: Any = 0) -> None:
        """Executa um movimento PTP."""
        self.robo.set_ptpcmd(
            ptp_mode=2,
            x=x,
            y=y,
            z=z,
            r=r,
            is_queued=True
        )

    def abrir_garra(self) -> None:
        """Abre a garra."""
        self.robo.set_endeffector_gripper(
            enable=True,
            on=False,
            is_queued=True
        )

    def fechar_garra(self) -> None:
        """Fecha a garra."""
        self.robo.set_endeffector_gripper(
            enable=True,
            on=True,
            is_queued=True
        )
