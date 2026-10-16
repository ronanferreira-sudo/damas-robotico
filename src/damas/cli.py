"""Ponto de entrada (CLI) do damas."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import warnings
from pathlib import Path

import yaml

# Silencia avisos de deprecacao de modulos do driver Dobot vendorizado.
warnings.filterwarnings("ignore", category=DeprecationWarning, module="damas.dobot")

logger = logging.getLogger("damas")


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_config(path: str | None) -> dict:
    root = _project_root()
    cfg_path = Path(path) if path else root / "config" / "default.yaml"
    if not cfg_path.exists():
        raise SystemExit(f"Arquivo de config nao encontrado: {cfg_path}")
    with open(cfg_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_calibration(path: str | None):
    if not path:
        return None
    from damas.vision.calibration import Calibration

    p = Path(path)
    if not p.exists():
        print(f"Calibracao nao encontrada: {p} (use 'damas calibrate').")
        return None
    return Calibration.load(str(p))


async def cmd_play(args) -> None:
    from damas.game import Match

    config = load_config(args.config)
    if args.mode:
        config["mode"] = args.mode

    # Sobrescreve parametros via flags da CLI
    if getattr(args, "max_moves", None) is not None:
        config.setdefault("match", {})["max_moves"] = args.max_moves
    if getattr(args, "white_port", None):
        config.setdefault("arms", {}).setdefault("white", {})["serial_port"] = args.white_port
    if getattr(args, "camera", None) is not None:
        config.setdefault("vision", {})["camera_index"] = args.camera

    calib = load_calibration(args.calibration)
    match = Match(config, calib)
    await match.setup()
    try:
        await match.run()
    finally:
        await match.teardown()



async def cmd_setup_arms(args) -> None:
    import sys
    sys.path.insert(0, str(_project_root()))
    from tools.arm_setup_gui import main as run_setup
    run_setup(args.config)


def cmd_play_gui(args) -> None:
    """Abre a interface gráfica para jogar Damas contra a IA com braço robótico."""
    import sys
    sys.path.insert(0, str(_project_root()))
    from tools.play_vs_ai_gui import PlayVsAIGUI
    app = PlayVsAIGUI(
        config_path=args.config,
        arm_color=getattr(args, "arm", "white"),
    )
    app.mainloop()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="damas", description="Damas robotico com I.A. e Dobot Magician Lite.")
    sub = p.add_subparsers(dest="command", required=True)

    play = sub.add_parser("play", help="Joga uma partida (simulacao ou hardware).")
    play.add_argument("--config", default=None)
    play.add_argument("--mode", choices=["simulation", "hardware"], default=None)
    play.add_argument("--max-moves", type=int, default=None,
                      help="Limite de lances (meios-lances). 0 = sem limite.")
    play.add_argument("--white-port", default=None,
                      help="Porta serial do braço branco (default: COM3).")
    play.add_argument("--calibration", default=None,
                      help="Caminho para o YAML de calibracao (camera + coordenadas).")
    play.set_defaults(func=cmd_play)

    play_gui = sub.add_parser(
        "play_gui",
        help="Abre a interface gráfica para jogar Damas contra a IA com braço robótico."
    )
    play_gui.add_argument("--config", default=None,
                          help="Caminho para o YAML de configuracao.")
    play_gui.add_argument("--arm", default="white", choices=["white"],
                          help="Braço físico disponível: branco (COM3).")
    play_gui.set_defaults(func=cmd_play_gui)

    setup = sub.add_parser("setup_arms", help="Abre a interface de configuracao manual dos bracos.")
    setup.add_argument("--config", default=None)
    setup.set_defaults(func=cmd_setup_arms)

    return p


def main() -> None:
    import inspect
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = build_parser()
    args = parser.parse_args()
    result = args.func(args)
    if inspect.iscoroutine(result):
        asyncio.run(result)


if __name__ == "__main__":
    main()
