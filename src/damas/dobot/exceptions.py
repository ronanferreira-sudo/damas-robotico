class DobotError(Exception):
    pass


class ConnectionError(DobotError):
    pass


class TimeoutError(DobotError):
    pass


class RPCError(DobotError):
    def __init__(self, code: int, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")