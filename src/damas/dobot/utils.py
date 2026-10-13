from typing import Any

from .exceptions import RPCError


def parse_result(response: Any) -> Any:
    if response is None:
        return None

    if isinstance(response, dict):
        if "result" in response:
            return response["result"]
        if "error" in response:
            error = response["error"]
            raise RPCError(
                error.get("code", -1),
                error.get("message", str(error))
            )

    return response
