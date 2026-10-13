"""Envia o braco branco Dobot Magician Lite para HOME.

Uso:
    python tools/home_white.py
    python tools/home_white.py --port COM3
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from damas.robot.arm import Arm

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("damas.home_white")


async def run(port: str) -> int:
    cfg = {
        "enabled": True,
        "connection": "usb",
        "serial_port": port or "auto",
        "origin_x": 120.0,
        "origin_y": -120.0,
        "spacing": 45.0,
        "travel_z": 60.0,
        "grip_z": 8.0,
        "capture_x": 250.0,
        "capture_y": -150.0,
        "capture_z": 8.0,
        "velocity": 60,
        "acceleration": 60,
        "effector": "suction",
    }
    arm = Arm("white", cfg, serial_port=port)
    try:
        logger.info("Conectando em %s ...", arm.serial_port)
        await arm.connect()
        logger.info("Enviando HOME ...")
        await arm.home()
        logger.info("HOME concluido.")
        return 0
    except Exception as exc:
        logger.error("Falha: %s", exc)
        return 1
    finally:
        try:
            await arm.disconnect()
        except Exception:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Envia o braco branco para HOME.")
    parser.add_argument("--port", default=None)
    args = parser.parse_args()
    return asyncio.run(run(args.port))


if __name__ == "__main__":
    sys.exit(main())
