"""Calibracao do tabuleiro sem janela grafica.

Salva N frames da camera em arquivos PNG. Voce escolhe o melhor frame e
informa os pixels dos 4 cantos (a1, a8, h1, h8) no console.

Uso:
    python tools/calibrate_headless.py
    python tools/calibrate_headless.py --camera 1 --frames 20
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import cv2
import numpy as np

from damas.vision.calibration import Calibration

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("damas.calibrate_headless")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Calibracao headless do tabuleiro.")
    p.add_argument("--camera", type=int, default=1)
    p.add_argument("--frames", type=int, default=20)
    p.add_argument("--output", default=None)
    p.add_argument("--roi-size", type=int, default=48)
    p.add_argument("--out-dir", default=None)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    out_dir = Path(args.out_dir) if args.out_dir else Path("captures")
    out_dir.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(args.camera, cv2.CAP_DSHOW)
    if not cap.isOpened():
        logger.error("Nao foi possivel abrir a camera %d.", args.camera)
        return 1
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    saved = []
    logger.info("Capturando %d frames em %s ...", args.frames, out_dir)
    for i in range(args.frames):
        ret, frame = cap.read()
        if not ret or frame is None:
            logger.warning("Frame %d falhou.", i)
            continue
        path = out_dir / f"capture_{i+1:03d}.png"
        cv2.imwrite(str(path), frame)
        saved.append(path)
        logger.info("Salvo: %s (mean=%.1f)", path.name, float(frame.mean()))
    cap.release()

    if not saved:
        logger.error("Nenhum frame capturado.")
        return 1

    print("\n=== Arquivos capturados ===")
    for i, p in enumerate(saved, 1):
        print(f"{i:02d}. {p.name}")
    print("Abra os arquivos e escolha o melhor frame para a calibracao.")
    print("Formato das coordenadas: u,v (pixels) separados por espaco/virgula.")
    print("Exemplo: a1 312,450  a8 290,120  h1 620,448  h8 598,118")

    choice = input("\nNome do arquivo escolhido (ex.: capture_001.png): ").strip()
    image_path = out_dir / choice
    if not image_path.exists():
        logger.error("Arquivo nao encontrado: %s", image_path)
        return 1

    def ask_corner(name: str) -> tuple[float, float]:
        while True:
            raw = input(f"{name} (u,v): ")
            parts = raw.replace(",", " ").split()
            if len(parts) != 2:
                print("Informe 2 numeros, ex.: 312 450")
                continue
            try:
                return float(parts[0]), float(parts[1])
            except ValueError:
                print("Valores invalidos.")

    print("\nInforme os centros dos 4 cantos na imagem:")
    a1 = ask_corner("a1")
    a8 = ask_corner("a8")
    h1 = ask_corner("h1")
    h8 = ask_corner("h8")

    calib = Calibration.build_from_corners(a1, a8, h1, h8, roi_size=args.roi_size)
    calib.empty_reference = str(image_path)
    output = Path(args.output) if args.output else Path("config/calibration.yaml")
    calib.save(str(output))
    print(f"\nCalibracao salva em {output}")
    print(f"Referencia vazia: {image_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
