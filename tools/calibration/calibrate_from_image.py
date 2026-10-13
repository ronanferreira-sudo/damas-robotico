"""Calibracao do tabuleiro por imagem salva (sem captura ao vivo).

Use quando a camera funciona no app Camera do Windows, mas o OpenCV
nao consegue capturar frames ao vivo.

Uso:
    python tools/calibrate_from_image.py --image foto_tabuleiro.png --output config/calibration.yaml
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
logger = logging.getLogger("damas.calibrate_image")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Calibracao do tabuleiro por imagem salva.")
    p.add_argument("--image", required=True, help="Caminho da foto do tabuleiro vazio.")
    p.add_argument("--output", default=None)
    p.add_argument("--roi-size", type=int, default=48)
    return p.parse_args()


def mouse_callback(event, x, y, flags, param):
    pts = param["points"]
    win = param["window"]
    if event == cv2.EVENT_LBUTTONDOWN:
        if len(pts) >= 4:
            pts.clear()
            if param["_frame"] is not None:
                param["frame"][:] = param["_frame"]
        pts.append((x, y))
        cv2.circle(param["frame"], (x, y), 6, (0, 0, 255), -1)
        label = ["a1", "a8", "h1", "h8"][min(len(pts) - 1, 3)]
        cv2.putText(param["frame"], label, (x + 10, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        cv2.imshow(win, param["frame"])
        logger.info("Clicou: %s (%d, %d) [%d/4]", label, x, y, len(pts))


def main() -> int:
    args = parse_args()
    output = Path(args.output) if args.output else Path("config/calibration.yaml")
    output.parent.mkdir(parents=True, exist_ok=True)

    image_path = Path(args.image)
    if not image_path.exists():
        logger.error("Imagem nao encontrada: %s", image_path)
        return 1

    img = cv2.imread(str(image_path))
    if img is None:
        logger.error("Falha ao carregar imagem: %s", image_path)
        return 1

    h, w = img.shape[:2]
    logger.info("Imagem carregada: %s (%dx%d)", image_path, w, h)

    win = "Calibracao por imagem - clique: a1, a8, h1, h8 | s=salvar | r=reset | q=sair"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(win, min(1280, w), min(720, h))
    cv2.moveWindow(win, 50, 50)

    state = {"points": [], "window": win, "frame": np.copy(img), "_frame": np.copy(img)}
    cv2.setMouseCallback(win, mouse_callback, state)

    logger.info("Clique nos cantos na ordem: a1 -> a8 -> h1 -> h8.")
    logger.info("Teclas: [s] salvar calibracao | [r] reset | [q] sair")

    while True:
        cv2.imshow(win, state["frame"])
        key = cv2.waitKey(30) & 0xFF
        if key == ord("q"):
            logger.info("Saindo sem salvar.")
            break
        if key == ord("r"):
            state["points"].clear()
            state["frame"][:] = np.copy(img)
            cv2.imshow(win, state["frame"])
            logger.info("Reset dos pontos.")
        if key == ord("s") and len(state["points"]) == 4:
            calib = Calibration.build_from_corners(*state["points"], roi_size=args.roi_size)
            calib.empty_reference = str(image_path)
            calib.save(str(output))
            logger.info("Calibracao salva em %s", output)
            logger.info("Referencia vazia: %s", image_path)
            break

    cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    sys.exit(main())
