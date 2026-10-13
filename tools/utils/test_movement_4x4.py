"""Teste de movimento de um braco Dobot numa grade 4x4.

Move pecas (pegar -> transportar -> soltar) entre os 16 quadrados de uma
grade 4x4, SEM logica de damas. Util para validar cinematica (origem,
espacamento, rotacao), alturas e end-effector antes de usar o tabuleiro
8x8 real com pecas verdadeiras.

A grade 4x4 usa os quadrados a1..d4 (16 posicoes).

Uso (execute uma vez para cada braco, com a origem/rotacao corretas):
    python tools/test_movement_4x4.py --port COM3
    python tools/test_movement_4x4.py --auto
    python tools/test_movement_4x4.py --port COM3 --touch
    python tools/test_movement_4x4.py --port COM3 --interactive
    python tools/test_movement_4x4.py --port COM3 --moves "a1 d1,d1 a4,a4 d4,d4 a1"

Coloque uma peca no quadrado a1 antes de rodar o demo (default), ou use
--touch para apenas sobrevoar os quadrados sem pegar nada.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from damas.robot.arm import Arm, find_all_dobot_ports
from damas.robot.kinematics import grid_squares

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("damas.test_movement_4x4")

FILES = 4
RANKS = 4
SQUARES = grid_squares(FILES, RANKS)

# Demo padrao: toca os 4 cantos da grade 4x4. Coloque uma peca em a1.
DEMO_MOVES = [("a1", "d1"), ("d1", "a4"), ("a4", "d4"), ("d4", "a1")]


def build_cfg(args: argparse.Namespace) -> dict:
    return {
        "enabled": True,
        "connection": "usb",
        "serial_port": "auto",
        "origin_x": args.origin_x,
        "origin_y": args.origin_y,
        "spacing": args.spacing,
        "rotation_deg": args.rotation,
        "travel_z": args.travel_z,
        "grip_z": args.grip_z,
        "capture_x": 250.0,
        "capture_y": -150.0,
        "capture_z": 8.0,
        "velocity": args.velocity,
        "acceleration": args.acceleration,
        "effector": args.effector,
    }


def parse_moves(spec: str) -> list[tuple[str, str]]:
    moves: list[tuple[str, str]] = []
    for chunk in spec.split(","):
        parts = chunk.split()
        if len(parts) == 2 and parts[0] in SQUARES and parts[1] in SQUARES:
            moves.append((parts[0], parts[1]))
        elif chunk.strip():
            logger.warning("Movimento ignorado (quadrado invalido): %s", chunk)
    return moves


async def run_demo(arm: Arm, moves: list[tuple[str, str]]) -> None:
    await arm.home()
    for frm, to in moves:
        logger.info("Movendo %s -> %s", frm, to)
        await arm.move_piece(frm, to)
        await asyncio.sleep(0.5)
    await arm.home()


async def run_touch(arm: Arm) -> None:
    await arm.home()
    for sq in SQUARES:
        logger.info("Sobrevoado %s", sq)
        await arm.approach(sq)
    await arm.home()


async def run_interactive(arm: Arm) -> None:
    await arm.home()
    print("Grade 4x4 (quadrados validos):", " ".join(SQUARES))
    print("Comandos:")
    print("  <de> <para>    move a peca (ex.: a1 d4)")
    print("  home           envia HOME")
    print("  touch [sq]     sobrevoa um quadrado (ou todos, sem argumento)")
    print("  quit           sai")
    while True:
        raw = await asyncio.get_event_loop().run_in_executor(None, input, "> ")
        parts = raw.strip().split()
        if not parts:
            continue
        cmd = parts[0].lower()
        if cmd in ("quit", "exit", "q"):
            break
        if cmd == "home":
            await arm.home()
        elif cmd == "touch":
            if len(parts) > 1 and parts[1] in SQUARES:
                await arm.approach(parts[1])
            else:
                await run_touch(arm)
        elif len(parts) >= 2 and parts[0] in SQUARES and parts[1] in SQUARES:
            await arm.move_piece(parts[0], parts[1])
        else:
            print("Comando invalido.")


async def run(args: argparse.Namespace, port: str) -> int:
    arm = Arm("4x4", build_cfg(args), serial_port=port)
    try:
        await arm.connect()
        if args.interactive:
            await run_interactive(arm)
        elif args.touch:
            await run_touch(arm)
        else:
            moves = parse_moves(args.moves) if args.moves else DEMO_MOVES
            await run_demo(arm, moves)
        return 0
    except Exception as exc:  # noqa: BLE001
        logger.error("Falha no teste: %s", exc)
        return 1
    finally:
        try:
            await arm.disconnect()
        except Exception:  # noqa: BLE001
            pass


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Teste de movimento de um braco Dobot numa grade 4x4."
    )
    parser.add_argument("--port", default=None, help="Porta serial (ex.: COM3)")
    parser.add_argument("--auto", action="store_true", help="Auto-detectar a porta serial")
    parser.add_argument("--origin-x", type=float, default=120.0, help="X do canto a1 (mm)")
    parser.add_argument("--origin-y", type=float, default=-120.0, help="Y do canto a1 (mm)")
    parser.add_argument("--spacing", type=float, default=45.0, help="Distancia entre centros (mm)")
    parser.add_argument("--rotation", type=float, default=0.0, help="Rotacao do tabuleiro (graus)")
    parser.add_argument("--travel-z", type=float, default=60.0, help="Altura de transporte (mm)")
    parser.add_argument("--grip-z", type=float, default=8.0, help="Altura de pegar/soltar (mm)")
    parser.add_argument("--velocity", type=float, default=60.0, help="Velocidade (0-100)")
    parser.add_argument("--acceleration", type=float, default=60.0, help="Aceleracao (0-100)")
    parser.add_argument(
        "--effector", default="suction", choices=["suction", "gripper"], help="End-effector"
    )
    parser.add_argument("--touch", action="store_true", help="Apenas sobrevoa os 16 quadrados")
    parser.add_argument("--interactive", action="store_true", help="Modo manual (digitacao)")
    parser.add_argument("--moves", default=None, help='Sequencia customizada "a1 d1,d1 a4"')
    args = parser.parse_args()

    port = args.port
    if not port and args.auto:
        ports = find_all_dobot_ports()
        if not ports:
            logger.error("Nenhuma porta serial encontrada.")
            return 1
        port = ports[0]
    if not port:
        logger.error("Informe --port ou use --auto.")
        return 2

    logger.info("Porta: %s | Grade %dx%d (%d quadrados)", port, FILES, RANKS, len(SQUARES))
    return asyncio.run(run(args, port))


if __name__ == "__main__":
    sys.exit(main())

