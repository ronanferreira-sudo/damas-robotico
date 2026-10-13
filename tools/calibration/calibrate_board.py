"""Calibracao interativa do tabuleiro usando a camera.

Uso:
    python tools/calibrate_board.py
    python tools/calibrate_board.py --camera 0 --output config/calibration.yaml

Passos:
1. Posicione o tabuleiro vazio sob a camera.
2. Clique nos 4 cantos na ordem: a1, a8, h1, h8.
3. Salve a imagem de referencia do tabuleiro vazio quando solicitado.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

import cv2
import numpy as np

from damas.vision.calibration import Calibration

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("damas.calibrate")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Calibracao do tabuleiro por camera.")
    p.add_argument("--camera", type=int, default=0)
    p.add_argument("--output", default=None)
    p.add_argument("--roi-size", type=int, default=48)
    p.add_argument("--warmup-frames", type=int, default=20)
    return p.parse_args()


def open_camera(index: int):
    cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
    if not cap.isOpened():
        logger.warning("CAP_DSHOW falhou, tentando backend padrao...")
        cap = cv2.VideoCapture(index)
    return cap


def put_status(img, text):
    cv2.putText(img, text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 255), 2)


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

    logger.info("Abrindo camera %d ...", args.camera)
    cap = open_camera(args.camera)
    if not cap.isOpened():
        logger.error("Nao foi possivel abrir a camera %d.", args.camera)
        return 1

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    cap.set(cv2.CAP_PROP_BRIGHTNESS, 180)
    cap.set(cv2.CAP_PROP_CONTRAST, 50)
    cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)
    cap.set(cv2.CAP_PROP_EXPOSURE, -4)

    try:
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        logger.info("Resolucao nativa: %dx%d", w, h)

        logger.info("Aquecendo camera (%d frames)...", args.warmup_frames)
        warmup = np.zeros((max(1, h), max(1, w), 3), dtype=np.uint8)
        for i in range(args.warmup_frames):
            ret, frame = cap.read()
            if ret and frame is not None:
                warmup = frame
            time.sleep(0.05)

        frame = np.copy(warmup)
        if frame is None or frame.size == 0:
            logger.error("Falha ao capturar frame apos aquecimento.")
            return 1

        win = "Calibracao - clique: a1, a8, h1, h8 | s=salvar | r=reset | q=sair"
        cv2.namedWindow(win, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(win, min(1280, frame.shape[1]), min(720, frame.shape[0]))
        cv2.moveWindow(win, 50, 50)

        state = {"points": [], "window": win, "frame": np.copy(frame), "_frame": np.copy(frame)}
        cv2.setMouseCallback(win, mouse_callback, state)

        logger.info("Posicione o tabuleiro vazio na camera.")
        logger.info("Clique nos cantos na ordem: a1 -> a8 -> h1 -> h8.")
        logger.info("Teclas: [s] salvar calibracao | [r] reset | [q] sair")

        while True:
            ret, frame = cap.read()
            if not ret or frame is None:
                logger.error("Falha ao ler frame da camera.")
                break
            frame = np.copy(frame)
            state["_frame"] = frame
            if not state["points"]:
                state["frame"][:] = frame
            cv2.imshow(win, state["frame"])
            key = cv2.waitKey(30) & 0xFF
            if key == ord("q"):
                logger.info("Saindo sem salvar.")
                break
            if key == ord("r"):
                state["points"].clear()
                state["frame"][:] = np.copy(frame)
                cv2.imshow(win, state["frame"])
                logger.info("Reset dos pontos.")
            if key == ord("s") and len(state["points"]) == 4:
                calib = Calibration.build_from_corners(*state["points"], roi_size=args.roi_size)
                calib.save(str(output))
                empty_path = output.parent / "board_empty.png"
                cv2.imwrite(str(empty_path), frame)
                calib.empty_reference = str(empty_path)
                calib.save(str(output))
                logger.info("Calibracao salva em %s", output)
                logger.info("Referencia vazia salva em %s", empty_path)
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    sys.exit(main())
