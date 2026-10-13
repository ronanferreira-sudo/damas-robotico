"""Envia os dois bracos Dobot Magician Lite para a posicao HOME.

Uso:
    python tools/home_arms.py
    python tools/home_arms.py --white-port COM3 --black-port COM5
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from damas.robot.arm import Arm, assign_auto_ports, find_all_dobot_ports

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("damas.home_arms")


async def run_home(white_port: str | None, black_port: str | None) -> int:
    arms_cfg = {
        "white": {
            "enabled": True,
            "connection": "usb",
            "serial_port": white_port or "auto",
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
        },
        "black": {
            "enabled": True,
            "connection": "usb",
            "serial_port": black_port or "auto",
            "origin_x": 120.0,
            "origin_y": 120.0,
            "spacing": 45.0,
            "travel_z": 60.0,
            "grip_z": 8.0,
            "capture_x": 250.0,
            "capture_y": 150.0,
            "capture_z": 8.0,
            "velocity": 60,
            "acceleration": 60,
            "effector": "suction",
        },
    }

    auto_ports = find_all_dobot_ports()
    logger.info("Portas Dobot encontradas: %s", auto_ports)
    if not white_port or not black_port:
        assignments = assign_auto_ports(["white", "black"], auto_ports)
        white_port = white_port or assignments.get("white", "auto")
        black_port = black_port or assignments.get("black", "auto")

    arms = []
    try:
        for color, port in (("white", white_port), ("black", black_port)):
            cfg = arms_cfg[color]
            arm = Arm(color, cfg, serial_port=port)
            logger.info("[%s] porta=%s", color, arm.serial_port)
            await arm.connect()
            arms.append(arm)

        logger.info("Enviando HOME para os dois bracos ...")
        await asyncio.gather(*(arm.home() for arm in arms))
        logger.info("HOME concluido.")
        return 0
    finally:
        for arm in arms:
            try:
                await arm.disconnect()
            except Exception:  # noqa: BLE001
                pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Envia os dois bracos Dobot para HOME.")
    parser.add_argument("--white-port", default=None)
    parser.add_argument("--black-port", default=None)
    args = parser.parse_args()
    return asyncio.run(run_home(args.white_port, args.black_port))


if __name__ == "__main__":
    sys.exit(main())
