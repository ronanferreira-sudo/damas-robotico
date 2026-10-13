"""Abstracao de camera.

Suporta camera real (OpenCV) e camera simulada (gera imagem sintetica a
partir de um tabuleiro verdadeiro) para permitir desenvolvimento e testes sem
hardware.
"""

from __future__ import annotations

import logging
from typing import Callable, Mapping

import numpy as np

logger = logging.getLogger(__name__)


class Camera:
    def __init__(self, cfg: Mapping) -> None:
        self.cfg = cfg
        self.index = int(cfg.get("camera_index", 0))
        self.width = int(cfg.get("width", 1280))
        self.height = int(cfg.get("height", 720))
        self.backend = str(cfg.get("_backend", "real"))
        self._cap = None
        # Provedor de "verdade" para o modo simulado.
        self._truth_provider: Callable[[], Mapping[str, str]] | None = None

    def open(self) -> None:
        if self.backend == "sim":
            logger.info("Camera simulada aberta (sem hardware).")
            return
        import cv2  # import tardio: so necessario em hardware

        self._cap = cv2.VideoCapture(self.index)
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        if not self._cap.isOpened():
            raise RuntimeError(f"Nao foi possivel abrir a camera {self.index}.")

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def set_truth_provider(self, fn: Callable[[], Mapping[str, str]]) -> None:
        self._truth_provider = fn

    def read(self):
        if self.backend == "sim":
            return self._render_synthetic()
        if self._cap is None:
            raise RuntimeError("Camera nao aberta. Chame open().")
        ok, frame = self._cap.read()
        return frame if ok else None

    # -- imagem sintetica ---------------------------------------------------

    def _render_synthetic(self):
        h, w = self.height, self.width
        img = np.zeros((h, w, 3), dtype=np.uint8)
        img[:] = (40, 40, 40)
        board_w = min(w, h) * 0.8
        sq = board_w / 8.0
        ox = (w - board_w) / 2
        oy = (h - board_w) / 2
        for rank in range(8):
            for f in range(8):
                light = (rank + f) % 2 == 0
                color = (235, 235, 235) if light else (70, 70, 70)
                x0 = int(ox + f * sq)
                y0 = int(oy + (7 - rank) * sq)
                cv2_rect(img, x0, y0, int(sq), int(sq), color)
        truth = self._truth_provider() if self._truth_provider else {}
        for sq_name, symbol in truth.items():
            f = ord(sq_name[0]) - ord("a")
            rank = int(sq_name[1]) - 1
            cx = int(ox + f * sq + sq / 2)
            cy = int(oy + (7 - rank) * sq + sq / 2)
            piece_color = (245, 245, 245) if symbol.isupper() else (20, 20, 20)
            cv2_circle(img, cx, cy, int(sq * 0.32), piece_color)
        return img


def cv2_rect(img, x, y, w, h, color):
    try:
        import cv2

        cv2.rectangle(img, (x, y), (x + w, y + h), color, -1)
    except Exception:  # pragma: no cover - fallback sem cv2
        img[y : y + h, x : x + w] = color


def cv2_circle(img, cx, cy, r, color):
    try:
        import cv2

        cv2.circle(img, (cx, cy), r, color, -1)
    except Exception:  # pragma: no cover
        img[cy - r : cy + r, cx - r : cx + r] = color
