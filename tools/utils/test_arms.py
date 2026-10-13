"""Teste individual dos bracos Dobot Magician Lite.

Uso:
    python tools/test_arms.py
    python tools/test_arms.py --port COM3
    python tools/test_arms.py --port COM5 --move

Passos:
1. Detecta portas seriais disponiveis.
2. Conecta em UM braco por vez (evita conflitos USB concorrentes).
3. Imprime pose atual.
4. Envia HOME (ou movimento simples se --move).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time

import serial.tools.list_ports

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("damas.test_arms")


def find_dobot_ports() -> list[str]:
    ports = list(serial.tools.list_ports.comports())
    detected: list[str] = []
    for p in ports:
        desc = (p.description or "").lower()
        if any(token in desc for token in ("dobot", "usb serial", "ch340", "cp210")):
            detected.append(p.device)
        elif p.device.lower().startswith(("com", "/dev/ttyusb", "/dev/ttyacm")):
            detected.append(p.device)
    return detected


async def test_port(port: str, do_move: bool) -> bool:
    try:
        from pydobot import Dobot

        logger.info("=== Testando %s ===", port)
        logger.info("Conectando...")
        bot = Dobot(port=port)
        time.sleep(0.5)

        logger.info("Lendo pose...")
        try:
            pose = bot.pose()
            logger.info("Pose: %s", pose)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Falha ao ler pose: %s", exc)
            pose = None

        if do_move:
            logger.info("Inicializando fila e velocidade...")
            try:
                bot._set_queued_cmd_start_exec()
                bot.speed(100, 100)
            except Exception as e:
                logger.warning("Aviso na inicializacao: %s", e)

            logger.info("Enviando HOME...")
            bot.move_to(x=227.53, y=0.0, z=140.83, r=0.0)
            time.sleep(5)
            logger.info("HOME enviado. Nova pose:")
            try:
                pose = bot.pose()
                logger.info("Pose: %s", pose)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Falha ao ler pose apos HOME: %s", exc)

            logger.info("Movendo para (200, 0, 50)...")
            bot.move_to(x=200, y=0, z=50, r=0)
            time.sleep(3)
            logger.info("Nova pose:")
            try:
                pose = bot.pose()
                logger.info("Pose: %s", pose)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Falha ao ler pose apos movimento: %s", exc)

        bot.close()
        logger.info("OK %s", port)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error("FALHA %s: %s", port, exc)
        return False


async def main() -> int:
    parser = argparse.ArgumentParser(description="Teste individual dos bracos Dobot.")
    parser.add_argument("--port", default=None, help="Porta serial especifica")
    parser.add_argument("--move", action="store_true", help="Executa HOME e movimento simples")
    args = parser.parse_args()

    ports = [args.port] if args.port else find_dobot_ports()
    if not ports:
        logger.error("Nenhuma porta serial encontrada.")
        return 1

    logger.info("Portas encontradas: %s", ports)
    ok = 0
    for port in ports:
        if await test_port(port, args.move):
            ok += 1
        logger.info("---")

    logger.info("Resumo: %d/%d OK", ok, len(ports))
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
