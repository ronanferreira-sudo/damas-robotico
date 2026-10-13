import logging
from typing import Any

logger = logging.getLogger(__name__)


class IO:
    """Entradas e saídas digitais/analógicas do robô."""

    def __init__(self, robot: Any) -> None:
        self.robot = robot

    async def do(self, index: int, value: int) -> Any:
        """Define o estado de uma saída digital.

        Args:
            index: Índice da saída digital (0-15).
            value: Valor a escrever (0 ou 1).

        Raises:
            ValueError: Se o índice ou valor estiverem fora do intervalo permitido.
        """
        if not 0 <= index <= 15:
            raise ValueError("IO index must be between 0 and 15")
        if value not in (0, 1):
            raise ValueError("IO value must be 0 or 1")
        logger.debug(f"SetDO index={index} value={value}")
        return await self.robot.command(
            "SetDO",
            index=index,
            status=int(value)
        )

    async def pwm(self, index: int, frequency: int, duty: int) -> Any:
        """Define um sinal PWM em uma saída.

        Args:
            index: Índice da saída (0-15).
            frequency: Frequência em Hz (1-100000).
            duty: Ciclo de trabalho em porcentagem (0-100).

        Raises:
            ValueError: Se algum parâmetro estiver fora do intervalo permitido.
        """
        if not 0 <= index <= 15:
            raise ValueError("IO index must be between 0 and 15")
        if frequency < 1 or frequency > 100000:
            raise ValueError("PWM frequency must be between 1 and 100000 Hz")
        if not 0 <= duty <= 100:
            raise ValueError("PWM duty cycle must be between 0 and 100")
        logger.debug(f"SetPWM index={index} freq={frequency} duty={duty}")
        return await self.robot.command(
            "SetPWM",
            index=index,
            frequency=frequency,
            dutyCycle=duty
        )

    async def di(self, index: int) -> Any:
        """Lê o estado de uma entrada digital.

        Args:
            index: Índice da entrada digital (0-15).

        Returns:
            Estado da entrada (0 ou 1).

        Raises:
            ValueError: Se o índice estiver fora do intervalo permitido.
        """
        if not 0 <= index <= 15:
            raise ValueError("IO index must be between 0 and 15")
        logger.debug(f"GetDI index={index}")
        return await self.robot.command(
            "GetDI",
            index=index
        )

    async def ai(self, index: int) -> Any:
        """Lê o valor de uma entrada analógica.

        Args:
            index: Índice da entrada analógica (0-15).

        Returns:
            Valor da entrada analógica.

        Raises:
            ValueError: Se o índice estiver fora do intervalo permitido.
        """
        if not 0 <= index <= 15:
            raise ValueError("IO index must be between 0 and 15")
        logger.debug(f"GetAI index={index}")
        return await self.robot.command(
            "GetAI",
            index=index
        )
