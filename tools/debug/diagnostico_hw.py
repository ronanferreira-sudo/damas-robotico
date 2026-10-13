"""Diagnostico completo do sistema Damas Robotico.

Verifica:
  - Portas seriais / bracos Dobot
  - Cameras disponiveis (salva preview de cada uma)
  - Calibracao carregada
  - Imagem de referencia vazia

Uso:
    python tools/diagnostico_hw.py
    python tools/diagnostico_hw.py --no-camera-preview
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("diagnostico")

ROOT = Path(__file__).resolve().parents[1]


# --- Cameras -------------------------------------------------------------------

def check_cameras(save_preview: bool = True) -> list[int]:
    """Retorna indices de cameras que conseguiram capturar um frame."""
    try:
        import cv2
    except ImportError:
        logger.error("OpenCV nao instalado.")
        return []

    found: list[int] = []
    print("\n--- Cameras ---")
    for i in range(6):
        cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
        ok, frame = cap.read()
        if ok and frame is not None:
            h, w = frame.shape[:2]
            print(f"  [OK] index {i}: {w}x{h}")
            if save_preview:
                fname = ROOT / f"cam_preview_{i}.png"
                cv2.imwrite(str(fname), frame)
                print(f"       -> preview salvo: {fname.name}")
            found.append(i)
        else:
            print(f"  [--] index {i}: sem resposta")
        cap.release()
    return found


# --- Bracos Dobot --------------------------------------------------------------

def check_serial_ports() -> list[str]:
    import serial.tools.list_ports
    ports = list(serial.tools.list_ports.comports())
    print("\n--- Portas seriais ---")
    found: list[str] = []
    for p in ports:
        print(f"  {p.device:8s}  {p.description}  HWID={p.hwid}")
        found.append(p.device)
    if not found:
        print("  (nenhuma porta serial encontrada)")
    return found


def test_dobot_port(port: str) -> bool:
    try:
        from pydobot import Dobot
        bot = Dobot(port=port)
        time.sleep(0.3)
        pose = bot.pose()
        bot.close()
        print(f"  [OK] {port}  pose=({pose[0]:.1f}, {pose[1]:.1f}, {pose[2]:.1f})")
        return True
    except Exception as exc:
        print(f"  [ER] {port}  erro: {exc}")
        return False


def check_arms(ports: list[str]) -> None:
    print("\n--- Bracos Dobot ---")
    if not ports:
        print("  Nenhuma porta para testar.")
        return
    for port in ports:
        test_dobot_port(port)


# --- Calibracao ----------------------------------------------------------------

def check_calibration() -> None:
    print("\n--- Calibracao ---")
    calib_path = ROOT / "config" / "calibration.yaml"
    if not calib_path.exists():
        print(f"  [ER] {calib_path.name} nao encontrado")
        return

    try:
        sys.path.insert(0, str(ROOT / "src"))
        from damas.vision.calibration import Calibration
        calib = Calibration.load(str(calib_path))
        n = len(calib.square_centers)
        print(f"  [OK] {calib_path.name} -- {n}/64 quadrados calibrados, ROI={calib.roi_size}px")
        if calib.empty_reference:
            ref = Path(calib.empty_reference)
            if not ref.is_absolute():
                ref = ROOT / ref
            if ref.exists():
                print(f"  [OK] empty_reference: {calib.empty_reference}")
            else:
                print(f"  [ER] empty_reference nao encontrado: {calib.empty_reference}")
        else:
            print("  [!!] empty_reference nao definido na calibracao")
    except Exception as exc:
        print(f"  [ER] Erro ao carregar calibracao: {exc}")


# --- Relatorio final -----------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnostico do Damas Robotico")
    parser.add_argument("--no-camera-preview", action="store_true",
                        help="Nao salva previews de camera")
    args = parser.parse_args()

    print("=" * 60)
    print("  DIAGNOSTICO -- Damas Robotico")
    print("=" * 60)

    cameras = check_cameras(save_preview=not args.no_camera_preview)
    ports = check_serial_ports()
    check_arms(ports)
    check_calibration()

    print("\n--- Resumo ---")
    print(f"  Cameras funcionando : {cameras}")
    print(f"  Portas seriais      : {ports}")

    print("\n--- Proximos passos ---")
    if len(cameras) >= 2:
        print("  [CAM] Varias cameras detectadas. Veja os arquivos cam_preview_N.png")
        print("        e anote qual indice aponta para o tabuleiro.")
    elif cameras:
        print(f"  [CAM] Camera no indice {cameras[0]}. Confira cam_preview_{cameras[0]}.png")
    else:
        print("  [ER]  Nenhuma camera funcionando!")

    if len(ports) >= 2:
        print(f"  [ROB] Dois bracos detectados: {ports}")
        print("        Confirme qual porta eh o braco BRANCO e qual eh o PRETO.")
        print("        Atualize config/default.yaml se necessario.")
    elif ports:
        print(f"  [!!]  Apenas um braco detectado: {ports}")
    else:
        print("  [ER]  Nenhum braco detectado!")

    empty = ROOT / "config" / "board_empty.png"
    if not empty.exists():
        print("\n  [!!] FALTANDO: config/board_empty.png (foto do tabuleiro vazio)")
        print("       Posicione o tabuleiro VAZIO na frente da camera e rode:")
        print("         .venv\\Scripts\\python.exe tools\\static_frame.py")
        print("       Renomeie o arquivo gerado para config/board_empty.png")

    print("\n  Para testar movimento dos bracos:")
    print("    .venv\\Scripts\\python.exe tools\\test_arms.py --move")
    print("\n  Para rodar a partida em hardware:")
    print("    .venv\\Scripts\\python.exe -m damas.cli play --mode hardware --calibration config/calibration.yaml")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
