"""Teste de conexao dos bracos Dobot Magician Lite.

Executa verificacao SEM movimentar o braco:
- lista portas seriais
- detecta automaticamente portas com 'dobot'/'usb serial'/'ch340'
- conecta em modo USB (pydobot)
- imprime pose atual

Uso:
    python tools/test_connection.py
    python tools/test_connection.py --port COM3
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

import serial.tools.list_ports

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("damas.test_connection")


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


def try_connect(port: str, baudrate: int = 115200):
    try:
        from pydobot import Dobot

        logger.info("Conectando em %s @ %d baud ...", port, baudrate)
        bot = Dobot(port=port)
        time.sleep(0.5)
        try:
            pose = bot.pose()
        except Exception as exc:  # noqa: BLE001
            pose = None
            logger.warning("Falha ao ler pose: %s", exc)
        try:
            bot.close()
        except Exception:  # noqa: BLE001
            pass
        return pose
    except Exception as exc:  # noqa: BLE001
        logger.error("Falha na conexao com %s: %s", port, exc)
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Teste de conexao dos bracos Dobot.")
    parser.add_argument("--port", default=None, help="Porta serial especifica (ex.: COM3)")
    parser.add_argument("--baudrate", type=int, default=115200)
    args = parser.parse_args()

    logger.info("=== Portas seriais disponiveis ===")
    ports = list(serial.tools.list_ports.comports())
    if not ports:
        logger.error("Nenhuma porta serial encontrada.")
        return 1
    for p in ports:
        logger.info(" - %s : %s", p.device, p.description)

    candidates = [args.port] if args.port else find_dobot_ports()
    if not candidates:
        logger.warning("Nenhuma porta tipica de Dobot detectada; tente informar --port.")
        return 2

    logger.info("=== Testando conexao (%d braco(s)) ===", len(candidates))
    ok = 0
    for port in candidates:
        pose = try_connect(port, args.baudrate)
        if pose is not None:
            logger.info("OK %s | pose=%s", port, pose)
            ok += 1
        else:
            logger.error("FALHA %s", port)

    logger.info("=== Resumo: %d/%d conexao(oes) OK ===", ok, len(candidates))
    return 0 if ok else 3


if __name__ == "__main__":
    sys.exit(main())
