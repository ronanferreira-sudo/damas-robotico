"""Calibracao igual ao teste direto que funcionou."""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

from damas.vision.calibration import Calibration


def main() -> int:
    cap = cv2.VideoCapture(1, cv2.CAP_DSHOW)
    if not cap.isOpened():
        print("FALHA: nao abriu camera")
        return 1

    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    print("1. opened=", cap.isOpened())
    import time
    time.sleep(1)
    ret, frame = cap.read()
    print("2. read=", ret, "mean=", round(frame.mean(), 1) if frame is not None else None)

    win = "Calibracao - clique: a1, a8, h1, h8 | s=salvar | r=reset | q=sair"
    cv2.namedWindow(win)
    cv2.moveWindow(win, 50, 50)

    points = []

    def mouse_cb(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            points.append((x, y))
            idx = len(points) - 1
            label = ["a1", "a8", "h1", "h8"][idx]
            cv2.circle(frame, (x, y), 6, (0, 0, 255), -1)
            cv2.putText(frame, label, (x + 10, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            cv2.imshow(win, frame)
            print(f"Clicou: {label} ({x}, {y}) [{len(points)}/4]")

    cv2.setMouseCallback(win, mouse_cb)

    print("3. janela aberta, pressione q para sair, s para salvar")
    cv2.imshow(win, frame)

    while True:
        if cv2.waitKey(1) & 0xFF == ord("q"):
            print("Saindo sem salvar.")
            break
        if cv2.waitKey(1) & 0xFF == ord("s") and len(points) == 4:
            output = Path("config/calibration.yaml")
            calib = Calibration.build_from_corners(*points, roi_size=48)
            calib.save(str(output))
            empty_path = Path("config/board_empty.png")
            cv2.imwrite(str(empty_path), frame)
            calib.empty_reference = str(empty_path)
            calib.save(str(output))
            print(f"Calibracao salva em {output}")
            print(f"Referencia vazia salva em {empty_path}")
            break

    cv2.destroyAllWindows()
    cap.release()
    print("4. fim")
    return 0


if __name__ == "__main__":
    sys.exit(main())
