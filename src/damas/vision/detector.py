"""Detector de estado do tabuleiro a partir de imagens da camera.

Metodos suportados:
- "template": diferenca da imagem atual contra uma referencia do tabuleiro
  vazio (subtracao de fundo) para detectar ocupacao, e brilho dos pixels da
  diferenca para inferir a cor da peca.
- "ground_truth": usa o tabuleiro verdadeiro (modo simulacao), sem camera.

A deteccao de *tipo* da peca (rei, torre, ...) fica como evolucao futura
(requer templates ou modelo de visao computacional treinado).
"""

from __future__ import annotations

import logging
from typing import Callable, Mapping

import cv2
import numpy as np

from .calibration import Calibration
from .camera import Camera

logger = logging.getLogger(__name__)


def _color_of(symbol: str) -> str | None:
    if not symbol:
        return None
    return "white" if symbol.isupper() else "black"


class BoardDetector:
    def __init__(self, calibration: Calibration, cfg: Mapping) -> None:
        self.calib = calibration
        self.threshold = float(cfg.get("occupancy_threshold", 0.18))
        self.method = str(cfg.get("method", "template"))
        self._empty_cache: dict[str, np.ndarray] | None = None

    def _crop(self, frame, center, size):
        u, v = int(center[0]), int(center[1])
        h, w = frame.shape[:2]
        half = size // 2
        u0, u1 = max(0, u - half), min(w, u + half)
        v0, v1 = max(0, v - half), min(h, v + half)
        roi = frame[v0:v1, u0:u1]
        if roi.shape[0] != size or roi.shape[1] != size:
            top = max(0, size//2 - v)
            bottom = max(0, v + size//2 - h)
            left = max(0, size//2 - u)
            right = max(0, u + size//2 - w)
            roi = cv2.copyMakeBorder(roi, top, bottom, left, right, cv2.BORDER_CONSTANT, value=0)
        return roi

    def _load_empty_reference(self) -> dict[str, np.ndarray]:
        if self._empty_cache is not None:
            return self._empty_cache
        self._empty_cache = {}
        path = self.calib.empty_reference
        if not path:
            return self._empty_cache
        try:
            img = cv2.imread(path)
            if img is None:
                return self._empty_cache
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            for sq, center in self.calib.square_centers.items():
                self._empty_cache[sq] = self._crop(gray, center, self.calib.roi_size)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Nao carregou referencia vazia: %s", exc)
        return self._empty_cache

    def detect(self, frame) -> dict[str, str | None]:
        if self.method != "template":
            raise ValueError(f"Metodo de deteccao nao suportado: {self.method}")
        if frame is None:
            return {}

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        empty = self._load_empty_reference()
        result: dict[str, str | None] = {}
        for sq, center in self.calib.square_centers.items():
            roi = self._crop(gray, center, self.calib.roi_size)
            if roi.size == 0:
                result[sq] = None
                continue
            if empty and sq in empty:
                diff = cv2.absdiff(roi, empty[sq])
                occ_score = float(np.mean(diff)) / 255.0
            else:
                occ_score = float(np.std(roi)) / 128.0
            if occ_score < self.threshold:
                result[sq] = None
                continue
            if empty and sq in empty:
                mask = diff > 25
                bright = float(np.mean(roi[mask])) if mask.any() else float(np.mean(roi))
            else:
                bright = float(np.mean(roi))
            result[sq] = "white" if bright > 128 else "black"
        return result


class VisionSystem:
    """Junta camera + detector e entrega o estado detectado do tabuleiro."""

    def __init__(self, cfg: Mapping, calibration: Calibration | None = None) -> None:
        self.cfg = cfg
        self.calib = calibration
        self.method = str(cfg.get("method", "template"))
        self.camera = Camera(cfg)
        self.detector = BoardDetector(calibration, cfg) if calibration else None

    def open(self) -> None:
        self.camera.open()

    def close(self) -> None:
        self.camera.close()

    def set_truth_provider(self, fn: Callable[[], Mapping[str, str]]) -> None:
        self.camera.set_truth_provider(fn)

    async def detect_board(self) -> dict[str, str | None]:
        if self.method == "ground_truth" or self.detector is None:
            truth = self.camera._truth_provider() if self.camera._truth_provider else {}
            return {sq: _color_of(sym) for sq, sym in truth.items()}
        frame = self.camera.read()
        return self.detector.detect(frame)
