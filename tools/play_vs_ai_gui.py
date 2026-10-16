"""Interface Gráfica para Jogar Damas Brasileiras contra a IA com Braço Robótico.

Fluxo do jogo:
  1. Usuário clica numa peça branca para selecioná-la (origem).
  2. Clica numa casa de destino válida (destacada em azul).
  3. Clica em "▶ JOGAR" para confirmar.
  4. O braço robótico executa o lance fisicamente (se conectado).
  5. A IA calcula e executa sua jogada.
  6. Ciclo repete até fim de jogo.

Uso:
    python tools/play_vs_ai_gui.py
    python tools/play_vs_ai_gui.py --config config/default.yaml --arm white
"""

from __future__ import annotations

import argparse
import math
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

import tkinter as tk
from tkinter import ttk, messagebox

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

CONFIG_PATH = ROOT / "config" / "default.yaml"

# ─── Imports do Pacote ────────────────────────────────────────────────────────

try:
    from damas.draughts.board_state import BoardState
    from damas.draughts.engine import choose_move
    from damas.game.match import plan_actions
    HAS_GAME = True
    _import_error = ""
except ImportError as _e:
    HAS_GAME = False
    _import_error = str(_e)
    BoardState = None
    choose_move = None
    plan_actions = None

# ─── Pydobot ─────────────────────────────────────────────────────────────────

try:
    from pydobot import Dobot as Pydobot
    from pydobot.enums import PTPMode
    from pydobot.message import Message
    from pydobot.enums.CommunicationProtocolIDs import CommunicationProtocolIDs
    from pydobot.enums.ControlValues import ControlValues
    HAS_PYDOBOT = True
except ImportError:
    HAS_PYDOBOT = False
    Pydobot = None
    PTPMode = None
    Message = None
    CommunicationProtocolIDs = None
    ControlValues = None

# ─── Mapeamento PDN → Casa (Damas Brasileiras 8×8) ───────────────────────────

PDN_TO_SQUARE: dict[int, str] = {}
SQUARE_TO_PDN: dict[str, int] = {}
DRAUGHTS_SQUARES: list[str] = []
INITIAL_POSITION = "W:Wa1,c1,e1,g1,b2,d2,f2,h2:Ba7,c7,e7,g7,b8,d8,f8,h8"

_pdn = 1
for _rank in range(1, 9):
    for _fi in range(8):
        _col = chr(ord("a") + _fi)
        _sq = f"{_col}{_rank}"
        if (_fi + _rank) % 2 == 1:          # casas escuras (jogáveis)
            DRAUGHTS_SQUARES.append(_sq)
            PDN_TO_SQUARE[_pdn] = _sq
            SQUARE_TO_PDN[_sq] = _pdn
            _pdn += 1


def _format_sq_display(sq: str) -> str:
    pdn = SQUARE_TO_PDN.get(sq.lower())
    return f"{sq.upper()} (PDN {pdn})" if pdn is not None else sq.upper()


def _parse_sq_display(text: str) -> str:
    if not text:
        return ""
    return text.split()[0].lower()


def find_dobot_ports() -> list[str]:
    # O único braço deste setup está conectado à COM3.
    return ["COM3"]
    try:
        import serial.tools.list_ports
        ports = list(serial.tools.list_ports.comports())
    except Exception:
        return ["COM3"]

    detected: list[str] = []
    others: list[str] = []
    for p in ports:
        desc = (p.description or "").lower()
        hwid = (p.hwid or "").lower()
        # 0483:5750 é o ID de hardware (USB VID:PID) do controlador STM32 do Dobot
        if "0483:5750" in hwid or any(tok in desc for tok in ("dobot", "usb serial", "ch340", "cp210")):
            detected.append(p.device)
        else:
            others.append(p.device)

    result = detected + others
    if "COM3" not in result:
        result.insert(0, "COM3")
    return result


# ─── Worker do Dobot ──────────────────────────────────────────────────────────

class DobotWorker:
    SERIAL_RESPONSE_TIMEOUT = 5.0

    def __init__(self, port: str, max_reach=380.0, min_reach=100.0,
                 z_min=-70.0, z_max=160.0):
        if not HAS_PYDOBOT:
            raise ImportError("pydobot não instalado. Execute: pip install pydobot")
        self.bot = Pydobot(port=port)
        # pydobot usa read_all() após uma pausa fixa de 100 ms; respostas USB
        # fragmentadas podem ser confundidas com ausência de resposta.
        self.bot._read_message = self._read_serial_message
        self.lock = threading.Lock()
        self.sucking = False
        self.max_reach = max_reach
        self.min_reach = min_reach
        self.z_min = z_min
        self.z_max = z_max
        self.last_serial_error = None

    def _read_serial_message(self):
        """Lê um quadro Dobot completo, tolerando respostas USB fragmentadas."""
        serial_conn = self.bot.ser
        previous_timeout = serial_conn.timeout
        # O controlador pode demorar mais para responder enquanto termina de
        # processar o movimento anterior. Não reenvie movimentos após timeout:
        # o primeiro comando pode já estar na fila do Dobot.
        deadline = time.monotonic() + self.SERIAL_RESPONSE_TIMEOUT
        header = bytearray()
        self.last_serial_error = None

        def read_exact(count: int) -> bytes | None:
            data = bytearray()
            while len(data) < count and time.monotonic() < deadline:
                chunk = serial_conn.read(count - len(data))
                if chunk:
                    data.extend(chunk)
            return bytes(data) if len(data) == count else None

        try:
            serial_conn.timeout = 0.05
            while time.monotonic() < deadline:
                byte = serial_conn.read(1)
                if not byte:
                    continue
                if byte[0] == 0xAA:
                    header.append(byte[0])
                    if len(header) == 2:
                        break
                else:
                    header.clear()

            if len(header) != 2:
                self.last_serial_error = (
                    f"nenhum quadro de resposta chegou em "
                    f"{self.SERIAL_RESPONSE_TIMEOUT:.0f} s"
                )
                return None

            length_bytes = read_exact(1)
            if length_bytes is None:
                self.last_serial_error = "quadro serial incompleto antes do campo de tamanho"
                return None
            frame_length = length_bytes[0]
            if frame_length < 2:
                self.last_serial_error = f"tamanho inválido no quadro serial: {frame_length}"
                return None

            body = read_exact(frame_length + 1)
            if body is None:
                self.last_serial_error = "quadro serial incompleto nos dados de resposta"
                return None
            return Message(bytes(header) + length_bytes + body)
        except Exception as exc:
            self.last_serial_error = f"erro ao ler a porta serial: {exc}"
            return None
        finally:
            serial_conn.timeout = previous_timeout

    def clear_alarms(self):
        """Limpa alarmes de sobrecorrente/limite do Dobot e reinicia a fila de comandos."""
        if not HAS_PYDOBOT:
            return
        try:
            with self.lock:
                msg = Message()
                msg.id = CommunicationProtocolIDs.CLEAR_ALL_ALARMS_STATE.value
                msg.ctrl = ControlValues.ONE.value
                self.bot._send_command(msg)
                self.bot._set_queued_cmd_clear()
                self.bot._set_queued_cmd_start_exec()
        except Exception:
            pass

    def get_pose(self):
        with self.lock:
            p = self.bot.pose()
            return (float(p[0]), float(p[1]), float(p[2]), float(p[3]))

    def move_to(self, x, y, z, r=0.0, timeout=12.0, joint=False):
        """Move o braço para (x, y, z, r) com espera real de parada física."""
        dist = math.sqrt(x * x + y * y)
        if dist > self.max_reach:
            raise ValueError(f"Fora do alcance máximo ({dist:.1f} > {self.max_reach:.0f} mm).")
        if dist < self.min_reach:
            raise ValueError(f"Muito próximo da base ({dist:.1f} < {self.min_reach:.0f} mm).")
        if not (self.z_min <= z <= self.z_max):
            raise ValueError(f"Z={z:.1f} fora dos limites [{self.z_min:.0f}, {self.z_max:.0f}] mm.")

        ptp_mode = PTPMode.MOVJ_XYZ if joint else PTPMode.MOVL_XYZ
        with self.lock:
            res = self.bot._set_ptp_cmd(x, y, z, r, mode=ptp_mode, wait=False)
        if res is None or not getattr(res, "params", None):
            raise TimeoutError(
                f"Sem resposta serial do Dobot ao enviar movimento para "
                f"X={x:.1f}, Y={y:.1f}, Z={z:.1f} na porta {self.bot.ser.port}. "
                f"Detalhe: {self.last_serial_error or 'resposta ausente ou vazia'}. "
                "O comando pode ter sido aceito; a fila foi preservada para evitar "
                "interromper um movimento em andamento."
            )

        if len(res.params) < 4:
            raise TimeoutError(
                f"Resposta serial incompleta do Dobot para X={x:.1f}, "
                f"Y={y:.1f}, Z={z:.1f} na porta {self.bot.ser.port} "
                f"({len(res.params)} de 4 bytes de índice)."
            )

        expected_idx = int.from_bytes(res.params[:4], byteorder="little", signed=False)
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                with self.lock:
                    cur = self.bot._get_queued_cmd_current_index()
                if cur >= expected_idx:
                    break
            except Exception:
                pass
            time.sleep(0.04)
        else:
            raise TimeoutError(
                f"A fila do Dobot não confirmou o movimento para "
                f"({x:.1f}, {y:.1f}, {z:.1f}) em {timeout:.0f} s. "
                "A fila foi preservada; verifique o braço e use o botão de limpar "
                "alarme somente depois de confirmar que ele parou."
            )

        # Aguarda o robô desacelerar e atingir a proximidade física do alvo
        t_settle = time.time()
        while time.time() - t_settle < 1.5:
            try:
                with self.lock:
                    p = self.bot.pose()
                dx = abs(p[0] - x)
                dy = abs(p[1] - y)
                dz = abs(p[2] - z)
                if dx < 6.0 and dy < 6.0 and dz < 6.0:
                    break
            except Exception:
                pass
            time.sleep(0.04)

        time.sleep(0.08)

    def set_suction(self, enable: bool):
        with self.lock:
            self.sucking = enable
            self.bot.suck(enable)

    def home(self):
        # Usa o mesmo fluxo de movimento da partida: valida os limites,
        # aguarda a fila do Dobot e confirma que o braço chegou ao destino.
        self.move_to(227.53, 0.0, 140.83, 0.0, joint=True)

    def close(self):
        try:
            with self.lock:
                self.bot.suck(False)
                self.bot.close()
        except Exception:
            pass


# ─── Executor de Lances ───────────────────────────────────────────────────────

class ArmExecutor:
    def __init__(self, worker: DobotWorker,
                 square_coords: dict[str, dict],
                 travel_z: float = 80.0,
                 capture_pos: tuple | None = None,
                 capture_stack_step_mm: float = 5.0,
                 capture_count: int = 0,
                 on_capture_count=None):
        self.worker = worker
        self.coords = square_coords
        self.travel_z = max(70.0, float(travel_z))
        self.capture_pos = capture_pos
        self.capture_stack_step_mm = max(0.0, float(capture_stack_step_mm))
        self.capture_count = max(0, int(capture_count))
        self.on_capture_count = on_capture_count

    def _coord(self, sq: str):
        c = self.coords.get(sq.lower()) or self.coords.get(sq.upper())
        if not c:
            raise ValueError(f"Casa {sq} não calibrada!")
        return c

    def ensure_safe_height(self):
        """Garante que o braço suba verticalmente ANTES de qualquer deslocamento horizontal."""
        try:
            p = self.worker.get_pose()
            if p[2] < (self.travel_z - 10.0):
                # Sobe na vertical nas mesmas coordenadas X, Y onde já se encontra
                self.worker.move_to(p[0], p[1], self.travel_z, p[3], joint=True)
        except Exception as exc:
            raise RuntimeError(
                f"Falha ao consultar a posição ou subir o braço antes do movimento: {exc}"
            ) from exc

    def _approach(self, sq: str) -> tuple[float, float, float, float, float]:
        """Calcula coordenadas da casa: (x, y, z_touch, z_pre, r)."""
        c = self._coord(sq)
        x = float(c["x"])
        y = float(c["y"])
        z_touch = float(c["z"])
        z_pre = z_touch + 18.0   # 18 mm acima da peça para aproximação reta
        r = float(c.get("r", 0.0))
        return x, y, z_touch, z_pre, r

    def _above(self, sq: str):
        c = self._coord(sq)
        safe_z = max(self.travel_z, float(c["z"]) + 45.0)
        self.worker.move_to(c["x"], c["y"], safe_z, c.get("r", 0.0), joint=True)

    def pick(self, sq: str):
        x, y, z_touch, z_pre, r = self._approach(sq)
        # 1. Garante que sobe se estiver baixo e navega pelo ar até a casa
        self.ensure_safe_height()
        self._above(sq)
        # 2. Desce até 18 mm acima da peça
        self.worker.move_to(x, y, z_pre, r, joint=True)
        # 3. Liga o vácuo ANTES de tocar para atrair a peça suavemente
        self.worker.set_suction(True)
        # 4. Desce os últimos 18 mm em linha 100% reta vertical (MOVL) sem fazer curva/arco
        self.worker.move_to(x, y, z_touch, r, joint=False)
        # Dá tempo para a ventosa formar vácuo antes de levantar a peça.
        time.sleep(0.8)
        # 5. Sobe 18 mm em linha vertical reta (MOVL) levantando a peça limpa
        self.worker.move_to(x, y, z_pre, r, joint=False)
        # 6. Sobe até a altura de voo segura
        self._above(sq)

    def place(self, sq: str):
        x, y, z_touch, z_pre, r = self._approach(sq)
        # 1. Já está sobre a casa na altura de voo
        # 2. Desce até 18 mm acima da casa
        self.worker.move_to(x, y, z_pre, r, joint=True)
        # 3. Desce os últimos 18 mm em linha reta vertical pura (MOVL) assentando a peça
        self.worker.move_to(x, y, z_touch, r, joint=False)
        time.sleep(0.15)
        # 4. Desliga o vácuo para soltar a peça
        self.worker.set_suction(False)
        time.sleep(0.35)
        # 5. Sobe 18 mm retos verticais para desacoplar a borracha
        self.worker.move_to(x, y, z_pre, r, joint=False)
        # 6. Sobe para a altura de voo segura
        self._above(sq)

    def move_piece(self, frm: str, to: str):
        self.pick(frm)      # Pega e SOBE até safe_z sobre 'frm'
        self._above(to)     # Voa em safe_z pelo ar até sobre 'to'
        self.place(to)      # Desce suavemente, solta e SOBE de volta sobre 'to'

    def remove_captured(self, sq: str):
        if not self.capture_pos:
            raise ValueError(
                "Destino das peças capturadas não calibrado. Use a tela de calibragem "
                "para gravar a bandeja antes de jogar."
            )
        cx, cy, cz = self.capture_pos[:3]
        cr = self.capture_pos[3] if len(self.capture_pos) > 3 else 0.0

        drop_z = cz + self.capture_count * self.capture_stack_step_mm
        max_allowed_drop = min(self.worker.z_max - 20.0, cz + 30.0)
        drop_z = max(self.worker.z_min, min(drop_z, max_allowed_drop))
        pre_drop_z = drop_z + 18.0

        safe_z = min(self.worker.z_max, max(self.travel_z, drop_z + 25.0))
        if safe_z <= drop_z + 5.0:
            safe_z = min(self.worker.z_max, drop_z + 15.0)

        self.pick(sq)       # Pega a capturada de forma suave e sobe
        self.worker.move_to(cx, cy, safe_z, cr, joint=True)       # Voa alto até a bandeja
        self.worker.move_to(cx, cy, pre_drop_z, cr, joint=True)   # Desce até 18 mm da pilha
        self.worker.move_to(cx, cy, drop_z, cr, joint=False)      # Assenta reto na pilha
        self.worker.set_suction(False)
        time.sleep(0.35)
        self.capture_count += 1
        if self.on_capture_count:
            self.on_capture_count(self.capture_count)
        self.worker.move_to(cx, cy, pre_drop_z, cr, joint=False)  # Sobe reto da pilha
        self.worker.move_to(cx, cy, safe_z, cr, joint=True)       # Sobe de volta da bandeja

    def execute_actions(self, actions: list, log_fn=None):
        for kind, color, a, b in actions:
            if log_fn:
                log_fn(f"  → {kind}: {a}" + (f" → {b}" if b else ""))
            try:
                if kind == "capture":
                    self.remove_captured(a)
                else:
                    self.move_piece(a, b)
            except Exception as exc:
                destination = f" → {b}" if b else ""
                raise RuntimeError(
                    f"Falha ao executar {kind} {a}{destination}: {exc}"
                ) from exc


# ─── GUI Principal ────────────────────────────────────────────────────────────

CELL  = 72          # tamanho original do tabuleiro (mantido)
BOARD = CELL * 8    # tamanho total do canvas

# Paleta de cores (totalmente controlada, ignora tema Windows)
C_LIGHT  = "#f0d9b5"   # casa clara
C_DARK   = "#b58863"   # casa escura (padrão)
C_SEL    = "#f6f669"   # casa selecionada (origem) — amarelo forte
C_DEST   = "#cdd16e"   # destino válido — verde-limão
C_LAST   = "#aaa23a"   # último lance
C_HOVER  = "#e8e07a"   # hover sobre destino válido
C_WHITE  = "#ffffff"   # peça branca
C_WKING  = "#ffe082"   # dama branca
C_BLACK  = "#222222"   # peça preta
C_BKING  = "#7b1fa2"   # dama preta
C_OUTLINE = "#333333"
C_KMARK   = "#e65100"  # marcação de dama


class PlayVsAIGUI(tk.Tk):
    """Interface para jogar Damas Brasileiras contra a IA."""

    def __init__(self, config_path: str | None = None, arm_color: str = "white"):
        super().__init__()
        self.title("Damas Brasileiras — Humano (Brancas) vs I.A. (Pretas)")
        self.geometry("960x720")
        self.minsize(900, 660)
        self.resizable(True, True)

        if not HAS_GAME:
            messagebox.showerror(
                "Erro de Importação",
                f"Não foi possível carregar os módulos do jogo:\n{_import_error}\n\n"
                "Verifique se o pacote está instalado (pip install -e .) e tente novamente."
            )
            self.destroy()
            return

        # ── Config ──
        cfg_file = Path(config_path) if config_path else CONFIG_PATH
        self.config_path = cfg_file
        self.config: dict = {}
        if cfg_file.exists():
            with open(cfg_file, "r", encoding="utf-8") as f:
                self.config = yaml.safe_load(f) or {}

        self.arm_color_var = tk.StringVar(value=arm_color)
        self.capture_stack_count = int(
            self.config.get("arms", {}).get(arm_color, {}).get("capture_stack_count", 0)
        )
        self.square_coords: dict[str, dict] = {}
        self._load_coords()

        # ── Estado Robô ──
        self.worker: DobotWorker | None = None
        self.executor: ArmExecutor | None = None
        self.is_connected = False
        self.robot_busy = False

        # ── Estado Jogo ──
        self.engine_cfg = self.config.get("engine", {})
        self.mode = "setup"                     # "setup" = repor peças / montagem; "play" = partida
        self.board_state = BoardState("W:W:B")  # Inicia com tabuleiro vazio para montagem
        self.human_color = "white"
        self.selected_from: str | None = None
        self.selected_to: str | None = None
        self.valid_dests: set[str] = set()      # destinos do lance atual
        self.last_move_sqs: list[str] = []
        self.game_over = False
        self.ai_thinking = False
        self.move_count = 0
        self.cell_size = CELL
        self.board_offset_x = 0
        self.board_offset_y = 0

        # ── Canvas items ──
        self._rect_id: dict[str, int] = {}     # sq → id do retângulo
        self._piece_id: dict[str, int] = {}    # sq → id do círculo
        self._king_id: dict[str, int] = {}     # sq → id da coroa
        self._hover_sq: str | None = None

        self._build_ui()
        self._draw_board()
        self._draw_pieces()
        self._update_status()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ─── Config ───────────────────────────────────────────────────────────────

    def _load_coords(self):
        self.square_coords.clear()
        color = self.arm_color_var.get()
        arm_cfg = self.config.get("arms", {}).get(color, {})
        self.capture_stack_count = int(arm_cfg.get("capture_stack_count", 0))
        for sq, pt in (arm_cfg.get("square_overrides") or {}).items():
            if isinstance(pt, dict) and "x" in pt:
                self.square_coords[sq.lower()] = {k: float(pt.get(k, 0.0)) for k in ("x","y","z","r")}
        for sq, pt in (arm_cfg.get("corners") or {}).items():
            sq_l = sq.lower()
            if isinstance(pt, dict) and "x" in pt and sq_l not in self.square_coords:
                self.square_coords[sq_l] = {k: float(pt.get(k, 0.0)) for k in ("x","y","z","r")}

        # Completa casas sem medição direta por interpolação bilinear dos
        # cantos. Os pontos medidos individualmente continuam prevalecendo.
        corners = self.square_coords
        corner_names = ("a1", "h1", "a8", "h8")
        if all(sq in corners for sq in corner_names):
            a1, h1, a8, h8 = (corners[sq] for sq in corner_names)
            for rank in range(1, 9):
                v = (rank - 1) / 7
                for file_index in range(8):
                    u = file_index / 7
                    sq = f"{chr(ord('a') + file_index)}{rank}"
                    if sq in corners:
                        continue
                    self.square_coords[sq] = {
                        axis: ((1-u)*(1-v)*a1[axis] + u*(1-v)*h1[axis]
                               + (1-u)*v*a8[axis] + u*v*h8[axis])
                        for axis in ("x", "y", "z", "r")
                    }

    # ─── Construção da UI ─────────────────────────────────────────────────────

    def _build_ui(self):
        style = ttk.Style(self)
        style.theme_use("clam")

        root_frame = ttk.Frame(self, padding=8)
        root_frame.pack(fill="both", expand=True)
        root_frame.columnconfigure(0, weight=3)
        root_frame.columnconfigure(1, weight=2)
        root_frame.rowconfigure(0, weight=1)

        right = ttk.Frame(root_frame)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)

        # ── Esquerda: tabuleiro ───────────────────────────────────────────────
        left = ttk.Frame(root_frame)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)

        ttk.Label(
            left,
            text="♟  DAMAS BRASILEIRAS  ♟   —   Você = Brancas  |  I.A. = Pretas",
            font=("Arial", 13, "bold"),
            foreground="#1a237e"
        ).grid(row=0, column=0, columnspan=2, pady=(0, 6))

        # Canvas do tabuleiro
        canvas_frame = tk.Frame(left, bd=3, relief="ridge")
        canvas_frame.grid(row=1, column=0, columnspan=2, sticky="nsew")
        canvas_frame.grid_columnconfigure(0, weight=1)
        canvas_frame.grid_rowconfigure(0, weight=1)

        self.canvas = tk.Canvas(
            canvas_frame,
            width=BOARD,
            height=BOARD,
            highlightthickness=0,
            cursor="hand2"
        )
        self.canvas.pack(fill="both", expand=True)

        self.canvas.bind("<Button-1>", self._on_canvas_click)
        self.canvas.bind("<Motion>",   self._on_canvas_hover)
        self.canvas.bind("<Leave>",    lambda e: self._clear_hover())
        self.canvas.bind("<Configure>", self._on_canvas_resize)

        # Indicadores de turno e confirmação do lance ficam ao lado do tabuleiro.
        self.lbl_turn = ttk.Label(
            right,
            text="🛠️  MODO REPOR PEÇAS — Tabuleiro Vazio",
            font=("Arial", 11, "bold"),
            foreground="#0277bd"
        )
        self.lbl_turn.grid(row=0, column=0, sticky="ew", pady=(0, 6))

        # Painel de lance
        move_panel = ttk.LabelFrame(right, text=" Lance Selecionado ", padding=8)
        move_panel.grid(row=1, column=0, sticky="ew", pady=(0, 6))

        sel_row = ttk.Frame(move_panel)
        sel_row.pack(fill="x")

        ttk.Label(sel_row, text="De:", font=("Arial", 10, "bold")).pack(side="left")
        self.lbl_from = ttk.Label(sel_row, text=" —— ", font=("Arial", 14, "bold"),
                                   foreground="#f57f17", width=5)
        self.lbl_from.pack(side="left", padx=(4, 12))

        ttk.Label(sel_row, text="Para:", font=("Arial", 10, "bold")).pack(side="left")
        self.lbl_to = ttk.Label(sel_row, text=" —— ", font=("Arial", 14, "bold"),
                                 foreground="#1565c0", width=5)
        self.lbl_to.pack(side="left", padx=(4, 16))

        self.lbl_hint = ttk.Label(move_panel, text="Clique numa casa para mover o robô ou em Habilitar para Jogar.",
                                   font=("Arial", 9), foreground="#546e7a",
                                   wraplength=285, justify="left")
        self.lbl_hint.pack(fill="x", pady=(4, 0))

        btn_row = ttk.Frame(move_panel)
        btn_row.pack(fill="x", pady=(8, 0))

        self.btn_play = tk.Button(
            btn_row,
            text="▶  JOGAR",
            bg="#2e7d32", fg="#ffffff",
            activebackground="#1b5e20", activeforeground="#ffffff",
            font=("Arial", 13, "bold"),
            relief="raised", pady=5, padx=18,
            command=self._on_play,
            cursor="hand2",
            state="disabled",
            disabledforeground="#aaaaaa"
        )
        self.btn_play.pack(fill="x", pady=(0, 5))

        btn_sub_row = ttk.Frame(btn_row)
        btn_sub_row.pack(fill="x")

        tk.Button(
            btn_sub_row,
            text="✖ Limpar",
            bg="#546e7a", fg="#ffffff",
            activebackground="#37474f", activeforeground="#ffffff",
            font=("Arial", 9, "bold"),
            relief="raised", pady=4, padx=4,
            command=self._clear_selection,
            cursor="hand2"
        ).pack(side="left", fill="x", expand=True, padx=(0, 2))

        tk.Button(
            btn_sub_row,
            text="🛠️ Repor Peças",
            bg="#0277bd", fg="#ffffff",
            activebackground="#01579b", activeforeground="#ffffff",
            font=("Arial", 9, "bold"),
            relief="raised", pady=4, padx=4,
            command=self._enter_setup_mode,
            cursor="hand2"
        ).pack(side="left", fill="x", expand=True, padx=(2, 2))

        tk.Button(
            btn_sub_row,
            text="🔄 Novo Jogo",
            bg="#1565c0", fg="#ffffff",
            activebackground="#0d47a1", activeforeground="#ffffff",
            font=("Arial", 9, "bold"),
            relief="raised", pady=4, padx=4,
            command=self._new_game,
            cursor="hand2"
        ).pack(side="right", fill="x", expand=True, padx=(2, 0))

        # Status
        status_fr = ttk.LabelFrame(right, text=" Status ", padding=8)
        status_fr.grid(row=2, column=0, sticky="ew", pady=(0, 6))
        status_fr.columnconfigure(0, weight=1)

        self.lbl_status = ttk.Label(status_fr, text="Aguardando...",
                                     font=("Arial", 10, "bold"), foreground="#1565c0",
                                     wraplength=280, justify="left")
        self.lbl_status.pack(fill="x")
        self.lbl_movecount = ttk.Label(status_fr, text="Lances: 0",
                                        font=("Arial", 9), foreground="#546e7a")
        self.lbl_movecount.pack(anchor="w", pady=(4, 0))

        # Conexão Dobot
        conn_fr = ttk.LabelFrame(right, text=" Braço Robótico (Dobot) ", padding=8)
        conn_fr.grid(row=3, column=0, sticky="ew", pady=(0, 6))
        conn_fr.columnconfigure(1, weight=1)

        row_port = ttk.Frame(conn_fr)
        row_port.grid(row=0, column=0, columnspan=3, sticky="ew")
        row_port.columnconfigure(1, weight=1)

        ttk.Label(row_port, text="Porta:").grid(row=0, column=0, sticky="w", padx=(0, 4))
        ports = find_dobot_ports()
        arm_cfg = self.config.get("arms", {}).get(self.arm_color_var.get(), {})
        default_port = arm_cfg.get("serial_port")
        if not default_port or default_port not in ports:
            default_port = ports[0] if ports else "COM3"
        self.port_var = tk.StringVar(value=default_port)

        self.cb_port = ttk.Combobox(row_port, textvariable=self.port_var, values=ports, width=8)
        self.cb_port.grid(row=0, column=1, sticky="ew", padx=(0, 4))

        ttk.Button(row_port, text="🔄", width=3, command=self._refresh_ports).grid(
            row=0, column=2, padx=(0, 4)
        )

        self.btn_connect = ttk.Button(row_port, text="Conectar", command=self._toggle_conn)
        self.btn_connect.grid(row=0, column=3)

        ttk.Label(conn_fr, text="Braço:").grid(row=1, column=0, sticky="w", pady=(4, 0))
        cb_arm = ttk.Combobox(conn_fr, textvariable=self.arm_color_var,
                               values=["white"], state="disabled", width=8)
        cb_arm.grid(row=1, column=1, sticky="ew", pady=(4, 0))
        cb_arm.bind("<<ComboboxSelected>>", lambda e: self._load_coords())

        self.lbl_conn = ttk.Label(conn_fr, text="Desconectado",
                                   foreground="#d32f2f", font=("Arial", 9, "bold"))
        self.lbl_conn.grid(row=2, column=0, columnspan=3, sticky="w", pady=(4, 0))

        self.var_robot = tk.BooleanVar(value=True)
        ttk.Checkbutton(conn_fr, text="Usar braço para executar os lances",
                         variable=self.var_robot).grid(
            row=3, column=0, columnspan=3, sticky="w", pady=(4, 0))

        # Repor Peças / Mover Robô
        pos_fr = ttk.LabelFrame(right, text=" Repor Peças / Mover Robô ", padding=8)
        pos_fr.grid(row=4, column=0, sticky="ew", pady=(0, 6))
        pos_fr.columnconfigure(2, weight=1)

        ttk.Label(pos_fr, text="Casa:").grid(row=0, column=0, sticky="w", padx=(0, 2))
        ttk.Button(pos_fr, text="◀", width=3, command=self._prev_robot_sq).grid(row=0, column=1, padx=(0, 2))

        sq_list = [_format_sq_display(PDN_TO_SQUARE[i]) for i in range(1, 33) if i in PDN_TO_SQUARE]
        self.target_sq_var = tk.StringVar(value=sq_list[0] if sq_list else "A1")
        self.cb_target_sq = ttk.Combobox(
            pos_fr,
            textvariable=self.target_sq_var,
            values=sq_list,
            state="readonly",
            width=12
        )
        self.cb_target_sq.grid(row=0, column=2, sticky="ew", padx=(0, 2))
        ttk.Button(pos_fr, text="▶", width=3, command=self._next_robot_sq).grid(row=0, column=3, padx=(2, 0))

        self.btn_move_to_sq = tk.Button(
            pos_fr,
            text="📍 MOVER ROBÔ ATÉ A CASA",
            bg="#0277bd", fg="#ffffff",
            activebackground="#01579b", activeforeground="#ffffff",
            font=("Arial", 10, "bold"),
            relief="raised", pady=4,
            command=self._move_robot_to_target_sq,
            cursor="hand2"
        )
        self.btn_move_to_sq.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(6, 4))

        aux_row = ttk.Frame(pos_fr)
        aux_row.grid(row=2, column=0, columnspan=4, sticky="ew")
        aux_row.columnconfigure(0, weight=1)
        aux_row.columnconfigure(1, weight=1)
        aux_row.columnconfigure(2, weight=1)

        ttk.Button(aux_row, text="⬆ Subir", command=self._lift_robot_arm).grid(row=0, column=0, sticky="ew", padx=1)
        self.btn_pump = tk.Button(
            aux_row,
            text="💨 Ventosa",
            bg="#eceff1",
            activebackground="#b0bec5",
            font=("Arial", 9),
            relief="raised",
            command=self._toggle_suction,
            cursor="hand2"
        )
        self.btn_pump.grid(row=0, column=1, sticky="ew", padx=1)
        ttk.Button(aux_row, text="🏠 Home", command=self._robot_home).grid(row=0, column=2, sticky="ew", padx=1)

        setup_acts = ttk.Frame(pos_fr)
        setup_acts.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(4, 0))
        setup_acts.columnconfigure(0, weight=1)
        setup_acts.columnconfigure(1, weight=1)
        setup_acts.columnconfigure(2, weight=1)

        ttk.Button(setup_acts, text="🗑️ Esvaziar", command=self._clear_board_for_setup).grid(row=0, column=0, sticky="ew", padx=1)
        ttk.Button(setup_acts, text="♟ Peças Iniciais", command=self._fill_initial_pieces).grid(row=0, column=1, sticky="ew", padx=1)
        ttk.Button(setup_acts, text="🗑️ Zerar Bandeja", command=self._reset_capture_count).grid(row=0, column=2, sticky="ew", padx=1)

        self.btn_unlock = tk.Button(
            pos_fr,
            text="🚨 DESTRAVAR ROBÔ (LIMPAR ALARME)",
            bg="#d32f2f", fg="#ffffff",
            activebackground="#b71c1c", activeforeground="#ffffff",
            font=("Arial", 9, "bold"),
            relief="raised", pady=3,
            command=self._clear_alarms_action,
            cursor="hand2"
        )
        self.btn_unlock.grid(row=4, column=0, columnspan=4, sticky="ew", pady=(4, 2))

        arm_cfg = self.config.get("arms", {}).get(self.arm_color_var.get(), {})
        cz = float(arm_cfg.get("capture_z", 24.0))
        self.lbl_tray_status = ttk.Label(
            pos_fr,
            text=f"Bandeja: {self.capture_stack_count} peças (Entrega Z = {cz:.1f} mm)",
            font=("Arial", 9),
            foreground="#2e7d32"
        )
        self.lbl_tray_status.grid(row=5, column=0, columnspan=4, sticky="w", pady=(3, 1))

        self.btn_enable_play = tk.Button(
            pos_fr,
            text="🎮 HABILITAR PARA JOGAR",
            bg="#2e7d32", fg="#ffffff",
            activebackground="#1b5e20", activeforeground="#ffffff",
            font=("Arial", 11, "bold"),
            relief="raised", pady=5,
            command=self._enable_play_mode,
            cursor="hand2"
        )
        self.btn_enable_play.grid(row=6, column=0, columnspan=4, sticky="ew", pady=(4, 0))

        # Configuração IA
        ai_fr = ttk.LabelFrame(right, text=" I.A. ", padding=8)
        ai_fr.grid(row=5, column=0, sticky="ew", pady=(0, 6))  # painel de configuração da IA
        ai_fr.columnconfigure(1, weight=1)

        ttk.Label(ai_fr, text="Profundidade:").grid(row=0, column=0, sticky="w")
        self.depth_var = tk.IntVar(value=int(self.engine_cfg.get("minimax_depth", 3)))
        ttk.Spinbox(ai_fr, from_=1, to=8, textvariable=self.depth_var, width=5).grid(
            row=0, column=1, sticky="w", padx=(6, 0))
        ttk.Label(ai_fr, text="(1=fácil, 6=difícil)", font=("Arial", 8)).grid(
            row=0, column=2, padx=4)

        # Legenda de cores
        leg_fr = ttk.LabelFrame(right, text=" Legenda ", padding=6)
        leg_fr.grid(row=6, column=0, sticky="ew", pady=(0, 6))

        legends = [
            (C_SEL,  "Casa selecionada (origem)"),
            (C_DEST, "Destinos válidos do lance"),
            (C_LAST, "Último lance jogado"),
        ]
        for color, text in legends:
            row = ttk.Frame(leg_fr)
            row.pack(fill="x", pady=1)
            lbl_c = tk.Label(row, bg=color, width=3, relief="solid", bd=1)
            lbl_c.pack(side="left", padx=(0, 6))
            ttk.Label(row, text=text, font=("Arial", 9)).pack(side="left")

        right.bind("<Configure>", self._on_sidebar_resize)

    # ─── Canvas: Tabuleiro ────────────────────────────────────────────────────

    def _sq_to_xy(self, sq: str) -> tuple[int, int]:
        """Retorna (x0, y0) pixel do canto superior-esquerdo da casa."""
        fi = ord(sq[0]) - ord("a")                  # 0-7 (a=0, h=7)
        rk = int(sq[1]) - 1                          # 0-7 (rank 1=0, rank 8=7)
        x0 = self.board_offset_x + fi * self.cell_size
        y0 = self.board_offset_y + (7 - rk) * self.cell_size  # rank 1 na base
        return x0, y0

    def _xy_to_sq(self, px: int, py: int) -> str | None:
        """Converte coordenada pixel do canvas em nome de casa."""
        px -= self.board_offset_x
        py -= self.board_offset_y
        if not (0 <= px < self.cell_size * 8 and 0 <= py < self.cell_size * 8):
            return None
        fi = px // self.cell_size
        rk = 7 - (py // self.cell_size)
        if not (0 <= fi <= 7 and 0 <= rk <= 7):
            return None
        return f"{chr(ord('a') + fi)}{rk + 1}"

    def _on_canvas_resize(self, event):
        """Redimensiona o tabuleiro mantendo as 64 casas quadradas."""
        available = min(event.width, event.height)
        new_cell_size = max(32, available // 8)
        new_offset_x = (event.width - new_cell_size * 8) // 2
        new_offset_y = (event.height - new_cell_size * 8) // 2
        if (new_cell_size, new_offset_x, new_offset_y) == (
            self.cell_size, self.board_offset_x, self.board_offset_y
        ):
            return
        self.cell_size = new_cell_size
        self.board_offset_x = new_offset_x
        self.board_offset_y = new_offset_y
        if hasattr(self, "board_state"):
            self._draw_board()
            self._draw_pieces()

    def _on_sidebar_resize(self, event):
        width = max(180, event.width - 40)
        if hasattr(self, "lbl_status"):
            self.lbl_status.configure(wraplength=width)
        if hasattr(self, "lbl_hint"):
            self.lbl_hint.configure(wraplength=width)

    def _is_playable(self, sq: str) -> bool:
        return sq in SQUARE_TO_PDN

    def _draw_board(self):
        """Desenha os 64 retângulos do tabuleiro."""
        self.canvas.delete("all")
        self._rect_id.clear()
        for rank in range(1, 9):
            for fi in range(8):
                sq = f"{chr(ord('a') + fi)}{rank}"
                x0, y0 = self._sq_to_xy(sq)
                x1, y1 = x0 + self.cell_size, y0 + self.cell_size
                is_dark = self._is_playable(sq)
                fill = C_DARK if is_dark else C_LIGHT
                rid = self.canvas.create_rectangle(
                    x0, y0, x1, y1,
                    fill=fill, outline="#555555", width=1,
                    tags=("sq", sq)
                )
                self._rect_id[sq] = rid

                # Número PDN nas casas escuras (canto inferior-direito)
                if is_dark:
                    pdn = SQUARE_TO_PDN[sq]
                    self.canvas.create_text(
                        x1 - 4, y1 - 4,
                        text=str(pdn),
                        font=("Arial", max(7, int(self.cell_size * 0.10))),
                        fill="#7a5533",
                        anchor="se",
                        tags=("pdn", sq)
                    )
                # Letras/números de coordenada na borda
                if fi == 0:
                    self.canvas.create_text(
                        x0 + 4, y0 + 4,
                        text=str(rank),
                        font=("Arial", max(8, int(self.cell_size * 0.12)), "bold"),
                        fill="#444444" if not is_dark else "#b58863",
                        anchor="nw"
                    )
                if rank == 1:
                    self.canvas.create_text(
                        x1 - 4, y1 - 14,
                        text=chr(ord("a") + fi),
                        font=("Arial", max(8, int(self.cell_size * 0.12)), "bold"),
                        fill="#444444" if not is_dark else "#b58863",
                        anchor="se"
                    )

    def _draw_pieces(self):
        """(Re)desenha todas as peças sobre o tabuleiro."""
        self.canvas.delete("piece")
        self._piece_id.clear()
        self._king_id.clear()

        pm = self.board_state.piece_map()
        margin = max(5, self.cell_size // 9)

        # Se estiver no modo setup com tabuleiro vazio, desenha marcações guias das posições iniciais
        if self.mode == "setup" and not pm:
            init_white = {"a1", "c1", "e1", "g1", "b2", "d2", "f2", "h2"}
            init_black = {"a7", "c7", "e7", "g7", "b8", "d8", "f8", "h8"}
            for sq in init_white:
                x0, y0 = self._sq_to_xy(sq)
                cx = x0 + self.cell_size // 2
                cy = y0 + self.cell_size // 2
                r = self.cell_size // 2 - margin
                self.canvas.create_oval(
                    cx - r, cy - r, cx + r, cy + r,
                    outline="#ffffff", fill="", width=2, dash=(4, 4),
                    tags=("piece", f"ghost_{sq}", sq)
                )
                self.canvas.create_text(
                    cx, cy, text="Branca", font=("Arial", max(7, int(self.cell_size * 0.11)), "bold"),
                    fill="#e0e0e0", tags=("piece", sq)
                )
            for sq in init_black:
                x0, y0 = self._sq_to_xy(sq)
                cx = x0 + self.cell_size // 2
                cy = y0 + self.cell_size // 2
                r = self.cell_size // 2 - margin
                self.canvas.create_oval(
                    cx - r, cy - r, cx + r, cy + r,
                    outline="#222222", fill="#424242", width=2, dash=(4, 4),
                    tags=("piece", f"ghost_{sq}", sq)
                )
                self.canvas.create_text(
                    cx, cy, text="Preta", font=("Arial", max(7, int(self.cell_size * 0.11)), "bold"),
                    fill="#cccccc", tags=("piece", sq)
                )
            return

        # Casas de origem do jogador da vez (para destacar com borda)
        is_human_turn = (self.board_state.turn_name == self.human_color
                         and not self.game_over and not self.ai_thinking and self.mode == "play")
        human_origins = self._all_legal_origins() if is_human_turn else set()

        # Determina quais casas têm peças do humano vs IA.
        # IMPORTANTE: no pydraughts, piece_map() usa "w"/"W" para draughts.WHITE
        # e "b"/"B" para draughts.BLACK. O "human_color" é "white", então
        # as peças do humano têm sym.lower()=="w" — mas verificamos também
        # pelos lances legais para não errar caso haja inversão de versão.
        #
        # Estratégia: se o turno é do humano, as casas em human_origins são
        # peças do humano. As demais casas com peças são da IA.
        # Se não é turno do humano, usamos piece_map normalmente.

        # Obtemos também as casas de origem dos lances QUANDO for vez da IA,
        # para colorir as peças dela corretamente.
        all_white_sqs = {sq for sq, sym in pm.items() if sym.lower() == "w"}
        all_black_sqs = {sq for sq, sym in pm.items() if sym.lower() == "b"}

        # No pydraughts, se turn_name=="white", os lances saem de posições
        # que no piece_map são "b". Detectamos isso:
        if human_origins and all(sq in all_black_sqs for sq in list(human_origins)[:1]):
            # piece_map invertido: "b" = humano (brancas), "w" = IA (pretas)
            human_sqs = all_black_sqs
            ai_sqs    = all_white_sqs
        else:
            human_sqs = all_white_sqs
            ai_sqs    = all_black_sqs

        for sq, sym in pm.items():
            x0, y0 = self._sq_to_xy(sq)
            cx = x0 + self.cell_size // 2
            cy = y0 + self.cell_size // 2
            r = self.cell_size // 2 - margin

            is_human_piece = sq in human_sqs
            is_king = sym.isupper()

            # Humano = peça branca/clara; IA = peça preta/escura
            if is_human_piece:
                fill_pc = C_WHITE
                outline  = "#333333"
                width    = 2
            else:
                fill_pc = C_BLACK
                outline  = "#888888"
                width    = 2

            # Peças jogáveis da vez: borda amarela grossa
            if sq in human_origins:
                outline = "#f9a825"
                width   = 3

            # Peça selecionada: borda azul grossa
            if sq == self.selected_from:
                outline = "#1565c0"
                width   = 4

            oid = self.canvas.create_oval(
                cx - r, cy - r, cx + r, cy + r,
                fill=fill_pc, outline=outline, width=width,
                tags=("piece", f"piece_{sq}", sq)
            )
            self._piece_id[sq] = oid

            # Coroa (dama): símbolo no centro
            if is_king:
                kid = self.canvas.create_text(
                    cx, cy,
                    text="♛",
                    font=("Arial", int(r * 0.85), "bold"),
                    fill=C_KMARK if is_human_piece else "#eeeeee",
                    tags=("piece", f"king_{sq}", sq)
                )
                self._king_id[sq] = kid

    def _color_sq(self, sq: str, fill: str):
        """Muda a cor de fundo de uma casa."""
        rid = self._rect_id.get(sq)
        if rid:
            self.canvas.itemconfig(rid, fill=fill)

    def _refresh_colors(self):
        """Atualiza as cores de todas as casas de acordo com o estado atual."""
        target_sq = self._get_selected_robot_sq()

        for sq in DRAUGHTS_SQUARES:
            if self.mode == "setup":
                fill = C_SEL if sq == target_sq else C_DARK
            else:
                if sq == self.selected_from:
                    fill = C_SEL
                elif sq == self.selected_to:
                    fill = C_DEST
                elif sq in self.valid_dests:
                    fill = C_DEST
                elif sq in self.last_move_sqs:
                    fill = C_LAST
                else:
                    fill = C_DARK
            self._color_sq(sq, fill)

        # Casas claras permanecem claras
        for rank in range(1, 9):
            for fi in range(8):
                sq = f"{chr(ord('a') + fi)}{rank}"
                if not self._is_playable(sq):
                    self._color_sq(sq, C_LIGHT)

    # ─── Eventos do Canvas ────────────────────────────────────────────────────

    def _on_canvas_click(self, event: tk.Event):
        if self.ai_thinking or self.robot_busy:
            return

        sq = self._xy_to_sq(event.x, event.y)
        if sq is None or not self._is_playable(sq):
            return

        self._set_robot_target_sq(sq)

        # Se estiver no modo setup / repor peças:
        if self.mode == "setup":
            self._refresh_colors()
            pdn = SQUARE_TO_PDN.get(sq, 0)
            self.lbl_hint.config(
                text=f"Casa {sq.upper()} (PDN {pdn}) selecionada. Clique em 'MOVER ROBÔ ATÉ A CASA' para posicionar a peça."
            )
            return

        if self.game_over:
            return
        if self.board_state.turn_name != self.human_color:
            return

        # Casas com peças do jogador atual (obtidas dos lances legais)
        human_origins = self._all_legal_origins()

        # ── Clicou numa peça que pode mover → seleciona como origem
        if sq in human_origins:
            routes = self._legal_from(sq)
            self.selected_from = sq
            self.selected_to = None
            self.valid_dests = {r[-1] for r in routes}
            self.lbl_from.config(text=f" {sq.upper()} ")
            self.lbl_to.config(text=" —— ")
            self.lbl_hint.config(text="Agora clique num destino destacado em verde.")
            self.btn_play.config(state="disabled")
            self._refresh_colors()
            self._draw_pieces()
            return

        # ── Já tem origem → tenta definir destino
        if self.selected_from:
            if sq in self.valid_dests:
                self.selected_to = sq
                self.lbl_to.config(text=f" {sq.upper()} ")
                self.lbl_hint.config(text='Confirme clicando em "▶ JOGAR".')
                self.btn_play.config(state="normal")
                self._refresh_colors()
                return
            elif sq in human_origins:
                # Muda a peça de origem para outra com lances
                routes = self._legal_from(sq)
                self.selected_from = sq
                self.selected_to = None
                self.valid_dests = {r[-1] for r in routes}
                self.lbl_from.config(text=f" {sq.upper()} ")
                self.lbl_to.config(text=" —— ")
                self.lbl_hint.config(text="Agora clique num destino destacado em verde.")
                self.btn_play.config(state="disabled")
                self._refresh_colors()
                self._draw_pieces()
                return
            else:
                self.lbl_hint.config(
                    text="Destino inválido. Clique num destino verde ou noutra peça."
                )
        else:
            self.lbl_hint.config(
                text="Esta casa não tem peça sua com lances disponíveis."
            )

    def _on_canvas_hover(self, event: tk.Event):
        if self.mode == "setup":
            return
        sq = self._xy_to_sq(event.x, event.y)
        if sq == self._hover_sq:
            return
        # Desfaz hover anterior
        if self._hover_sq:
            prev = self._hover_sq
            self._hover_sq = None
            self._refresh_sq_color(prev)
        self._hover_sq = sq
        if sq and sq in self.valid_dests and sq != self.selected_to:
            self._color_sq(sq, C_HOVER)

    def _clear_hover(self):
        if self._hover_sq:
            prev = self._hover_sq
            self._hover_sq = None
            self._refresh_sq_color(prev)

    def _refresh_sq_color(self, sq: str):
        if sq == self.selected_from:
            self._color_sq(sq, C_SEL)
        elif sq == self.selected_to:
            self._color_sq(sq, C_DEST)
        elif sq in self.valid_dests:
            self._color_sq(sq, C_DEST)
        elif sq in self.last_move_sqs:
            self._color_sq(sq, C_LAST)
        elif self._is_playable(sq):
            self._color_sq(sq, C_DARK)

    # ─── Lógica de Lances ─────────────────────────────────────────────────────

    def _move_squares(self, move) -> list[str]:
        """Extrai lista de casas de um lance (PDN '9-13' ou '9x18x27')."""
        pdn = getattr(move, "pdn_move", "") or ""
        sep = "x" if "x" in pdn else "-"
        result = []
        for part in pdn.split(sep):
            try:
                n = int(part.strip())
                sq = PDN_TO_SQUARE.get(n)
                if sq:
                    result.append(sq)
            except ValueError:
                pass
        return result

    def _legal_from(self, sq: str) -> list[list[str]]:
        """Retorna lista de rotas legais que partem de `sq`."""
        results = []
        for mv in self.board_state.legal_moves():
            sqs = self._move_squares(mv)
            if sqs and sqs[0] == sq:
                results.append(sqs)
        return results

    def _all_legal_origins(self) -> set[str]:
        """Retorna todas as casas de origem dos lances legais do turno atual.
        Usado para detectar cliques em peças válidas sem depender do piece_map
        (que tem a convenção W/B invertida no pydraughts)."""
        origins: set[str] = set()
        for mv in self.board_state.legal_moves():
            sqs = self._move_squares(mv)
            if sqs:
                origins.add(sqs[0])
        return origins

    def _find_move(self, frm: str, to: str):
        """Encontra o objeto Move legal de `frm` para `to`."""
        for mv in self.board_state.legal_moves():
            sqs = self._move_squares(mv)
            if sqs and sqs[0] == frm and sqs[-1] == to:
                return mv
        return None

    # ─── Execução do Lance ────────────────────────────────────────────────────

    def _on_play(self):
        if not self.selected_from or not self.selected_to:
            return
        if self.game_over or self.ai_thinking or self.robot_busy:
            return

        chosen = self._find_move(self.selected_from, self.selected_to)
        if chosen is None:
            messagebox.showwarning("Lance inválido", "Este lance não está entre os lances legais.")
            self._clear_selection()
            return

        robot_requested = self.var_robot.get()
        if robot_requested and (not self.is_connected or not self.executor):
            messagebox.showerror(
                "Braço desconectado",
                "A opção de executar com o braço está marcada, mas o Dobot não está conectado.\n"
                "Conecte o braço antes de confirmar a jogada.",
            )
            self._log("Jogada não enviada: Dobot desconectado.", "robot")
            return

        self._set_locked(True)
        use_robot = robot_requested
        self.robot_busy = bool(use_robot)
        self._log(f"\n── Lance {self.move_count + 1} ──", "info")

        def _thread():
            try:
                san = self.board_state.san(chosen)
                sqs = self._move_squares(chosen)
                # Use o mesmo diff de tabuleiro da IA: ele encontra todas as
                # peças removidas, mesmo em captura múltipla ou com dama.
                previous_map = self.board_state.piece_map()
                next_state = self.board_state.copy()
                next_state.apply(chosen)
                actions = plan_actions(previous_map, next_state.piece_map())
                if use_robot:
                    self.executor.execute_actions(
                        actions,
                        log_fn=lambda m: self.after(0, lambda msg=m: self._log(msg, "robot")),
                    )
                self.board_state.apply(chosen)
                self.move_count += 1

                self.after(0, lambda: self._log(f"♟ Brancas: {san}", "white"))
                self.after(0, lambda: self._set_last(sqs))
                self.after(0, lambda: self._log("Comandos do braço concluídos; fila do Dobot confirmada.", "robot") if use_robot else None)

                self.after(0, self._after_human)
            except Exception as exc:
                self.after(0, lambda e=str(exc): self._show_error_alert("Erro no movimento do braço", e))
                self.after(0, self._on_human_move_failed)

        threading.Thread(target=_thread, daemon=True).start()

    def _on_human_move_failed(self):
        self.robot_busy = False
        self._set_locked(False)

    def _after_human(self):
        self.robot_busy = False
        self._clear_selection()
        self._refresh_colors()
        self._draw_pieces()
        self._update_movecount()

        # Vitória somente quando todas as peças do adversário foram capturadas
        if self._check_capture_win() is not None:
            self._announce_winner()
            return

        self.ai_thinking = True
        self.lbl_turn.config(text="I.A. pensando...", foreground="#c62828")
        self._update_status()
        self._log("🤔 I.A. calculando...", "info")
        threading.Thread(target=self._ai_thread, daemon=True).start()

    def _ai_thread(self):
        try:
            move = choose_move(
                self.board_state,
                backend="auto",
                stockfish_path=self.engine_cfg.get("stockfish_path"),
                think_time=float(self.engine_cfg.get("think_time", 1.0)),
                minimax_depth=self.depth_var.get()
            )
            if move is None:
                self.after(0, lambda: self._finish_ai_forfeit("A IA não encontrou uma jogada válida."))
                return

            san = self.board_state.san(move)
            sqs = self._move_squares(move)
            prev = self.board_state.piece_map()
            next_state = self.board_state.copy()
            next_state.apply(move)
            new_map = next_state.piece_map()
            actions = plan_actions(prev, new_map)
            robot_requested = self.var_robot.get()
            if robot_requested and (not self.is_connected or not self.executor):
                raise RuntimeError("Dobot desconectado; jogada da I.A. não foi enviada ao braço.")
            use_robot = robot_requested
            if use_robot:
                self.robot_busy = True
                self.after(0, lambda: self._log("🤖 Braço (IA)...", "robot"))
                self.executor.execute_actions(
                    actions,
                    log_fn=lambda m: self.after(0, lambda msg=m: self._log(msg, "robot"))
                )
                self.robot_busy = False

            self.board_state.apply(move)
            self.move_count += 1
            self.after(0, lambda: self._log(f"🤖 Pretas (I.A.): {san}", "black"))
            self.after(0, lambda: self._set_last(sqs))
            if use_robot:
                self.after(0, lambda: self._log("Comandos do braço concluídos; fila do Dobot confirmada.", "robot"))

            self.after(0, self._after_ai)
        except Exception as exc:
            self.after(0, lambda e=str(exc): self._finish_ai_forfeit(e))

    def _finish_ai_forfeit(self, reason: str):
        self.ai_thinking = False
        self.robot_busy = False
        self.game_over = True
        msg = (
            f"Ocorreu um erro durante a jogada da I.A.:\n\n{reason}\n\n"
            "O jogo foi pausado para evitar movimentos incorretos.\n"
            "Você pode clicar em 'Repor Peças' para reorganizar o tabuleiro ou em 'Novo Jogo'."
        )
        self.lbl_turn.config(text="Erro durante jogada da I.A.", foreground="#d32f2f")
        self.lbl_status.config(text=f"Erro da I.A.: {reason}", foreground="#d32f2f")
        self._set_locked(False)
        self._log(msg, "error")
        self._show_error_alert("Erro na jogada da IA", msg)

    def _show_error_alert(self, title: str, reason: str):
        """Mostra a falha na janela e no console, mesmo quando veio de uma thread."""
        if threading.current_thread() is not threading.main_thread():
            self.after(0, lambda: self._show_error_alert(title, reason))
            return
        try:
            self.lbl_status.config(text=f"ERRO: {reason}", foreground="#d32f2f")
            self.lbl_turn.config(text="Falha no movimento do robô", foreground="#d32f2f")
        except Exception:
            pass
        print(f"[{title}] {reason}", file=sys.stderr, flush=True)
        messagebox.showerror(title, reason, parent=self)

    def _after_ai(self):
        self.ai_thinking = False
        self._refresh_colors()
        self._draw_pieces()
        self._update_movecount()
        self._set_locked(False)

        # Vitória somente quando todas as peças do adversário foram capturadas
        if self._check_capture_win() is not None:
            self._announce_winner()
            return

        self.lbl_turn.config(text="▶  Sua vez — clique numa peça BRANCA", foreground="#2e7d32")
        self._update_status()
        self._log("--- Sua vez! ---", "info")

    def _set_last(self, sqs: list[str]):
        self.last_move_sqs = sqs
        self._refresh_colors()

    # ─── Utilitários de Estado ────────────────────────────────────────────────

    def _clear_selection(self):
        self.selected_from = None
        self.selected_to = None
        self.valid_dests = set()
        self.lbl_from.config(text=" —— ")
        self.lbl_to.config(text=" —— ")
        self.lbl_hint.config(text="Clique numa peça branca para começar.")
        self.btn_play.config(state="disabled")
        self._refresh_colors()

    def _set_locked(self, locked: bool):
        state = "disabled" if locked else "normal"
        self.btn_play.config(state="disabled")  # só habilita com seleção válida

    def _update_status(self):
        if self.game_over:
            return
        if self.ai_thinking:
            self.lbl_status.config(text="Aguardando a I.A...", foreground="#e65100")
        elif self.board_state.turn_name == self.human_color:
            n = len(self.board_state.legal_moves())
            self.lbl_status.config(
                text=f"✅ Sua vez! {n} lances disponíveis.", foreground="#2e7d32")
        else:
            self.lbl_status.config(text="Vez da I.A...", foreground="#e65100")

    def _update_movecount(self):
        self.lbl_movecount.config(text=f"Lances: {self.move_count}")

    def _check_capture_win(self) -> str | None:
        """Retorna 'human', 'ai', ou None.

        Só declara vencedor quando UM jogador capturou TODAS as peças do
        adversário. Erros do braço, ausência de lances legais e outros
        estados de jogo NÃO acionam esta função.
        """
        if self.mode != "play":
            return None

        pm = self.board_state.piece_map()
        white_count = sum(1 for sym in pm.values() if sym.lower() == "w")
        black_count = sum(1 for sym in pm.values() if sym.lower() == "b")

        # O Humano joga com as Brancas ('w') e a I.A. joga com as Pretas ('b')
        if black_count == 0 and white_count > 0:
            return "human"

        if white_count == 0 and black_count > 0:
            return "ai"

        return None  # Jogo ainda em andamento

    def _announce_winner(self):
        winner = self._check_capture_win()
        if winner is None:
            # Nenhuma peça foi completamente capturada — não anuncia.
            return

        self.game_over = True

        if winner == "human":
            msg = "🏆 VOCÊ VENCEU!\nVocê capturou todas as peças da I.A.!"
            fg = "#2e7d32"
        else:
            msg = "😔 VOCÊ PERDEU!\nA I.A. capturou todas as suas peças."
            fg = "#c62828"

        self.lbl_turn.config(text=msg, foreground=fg)
        self.lbl_status.config(text=msg, foreground=fg)
        self._log(f"\n{'='*30}", "info")
        self._log(msg, "win")
        self._log(f"{'='*30}", "info")
        messagebox.showinfo("Fim de Jogo", msg)

    def _new_game(self):
        if self.ai_thinking or self.robot_busy:
            if not messagebox.askyesno("Nova partida",
                                        "Um lance está em progresso. Deseja reiniciar mesmo assim?"):
                return
        self.mode = "play"
        self.board_state = BoardState(INITIAL_POSITION)
        self.selected_from = None
        self.selected_to = None
        self.valid_dests = set()
        self.last_move_sqs = []
        self.game_over = False
        self.ai_thinking = False
        self.robot_busy = False
        self.move_count = 0

        self._reset_capture_count_silent()

        self.lbl_from.config(text=" —— ")
        self.lbl_to.config(text=" —— ")
        self.lbl_hint.config(text="Clique numa peça branca para começar.")
        self.btn_play.config(state="disabled")
        self.lbl_turn.config(text="▶  Sua vez — clique numa peça BRANCA", foreground="#2e7d32")
        self.lbl_movecount.config(text="Lances: 0")
        if hasattr(self, "btn_enable_play"):
            self.btn_enable_play.config(state="disabled", text="✔ Jogo Habilitado", bg="#78909c")

        self._draw_board()
        self._draw_pieces()
        self._update_status()
        self._refresh_colors()
        self._log("=== Nova Partida ===", "info")
        self._log("Você joga com as BRANCAS.", "white")
        self._log("I.A. joga com as PRETAS.", "black")

    # ─── Log ──────────────────────────────────────────────────────────────────

    def _log(self, msg: str, tag: str = "info"):
        # Os detalhes ficam fora da interface; status e avisos seguem visíveis.
        return

    # ─── Conexão Dobot ────────────────────────────────────────────────────────

    def _refresh_ports(self):
        ports = find_dobot_ports()
        if hasattr(self, "cb_port"):
            self.cb_port.config(values=ports)
            if self.port_var.get() not in ports and ports:
                self.port_var.set(ports[0])

    def _toggle_conn(self):
        if self.is_connected:
            self._disconnect()
        else:
            self._connect()

    def _connect(self):
        if not HAS_PYDOBOT:
            messagebox.showerror("pydobot não instalado",
                                  "Instale com: pip install pydobot")
            return
        port = self.port_var.get().strip()
        self.lbl_conn.config(text="Conectando...", foreground="#e65100")
        self.btn_connect.config(state="disabled")

        arm_cfg = self.config.get("arms", {}).get(self.arm_color_var.get(), {})
        arm_color = self.arm_color_var.get()
        limits = arm_cfg.get("limits", {})

        def _do():
            try:
                w = DobotWorker(
                    port,
                    max_reach=float(limits.get("max_reach_mm", 380.0)),
                    min_reach=float(limits.get("min_reach_mm", 100.0)),
                    z_min=float(limits.get("z_min_mm", -70.0)),
                    z_max=float(limits.get("z_max_mm", 160.0)),
                )
                self.worker = w
                travel_z = float(arm_cfg.get("travel_z", 80.0))
                cap = None
                if all(f"capture_{axis}" in arm_cfg for axis in ("x", "y", "z")):
                    cap = (float(arm_cfg["capture_x"]),
                           float(arm_cfg["capture_y"]),
                           float(arm_cfg["capture_z"]),
                           float(arm_cfg.get("capture_r", 0.0)))
                stack_step = float(arm_cfg.get("capture_stack_step_mm", 5.0))
                self.executor = ArmExecutor(
                    w, self.square_coords, travel_z, cap, stack_step,
                    self.capture_stack_count,
                    lambda count, color=arm_color: self._update_capture_stack_count(color, count),
                )
                self.is_connected = True
                self.after(0, self._on_connected)
            except Exception as e:
                err = str(e)
                self.after(0, lambda: self._on_conn_fail(err))

        threading.Thread(target=_do, daemon=True).start()

    def _update_capture_stack_count(self, color: str, count: int):
        self.capture_stack_count = count
        self.config.setdefault("arms", {}).setdefault(color, {})["capture_stack_count"] = count
        tmp_path = None
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.config_path.parent,
                prefix=f"{self.config_path.stem}_", suffix=".tmp", delete=False,
            ) as tmp_file:
                tmp_path = Path(tmp_file.name)
                yaml.safe_dump(
                    self.config, tmp_file, sort_keys=False,
                    default_flow_style=False, allow_unicode=True,
                )
                tmp_file.flush()
                os.fsync(tmp_file.fileno())
            os.replace(tmp_path, self.config_path)
            tmp_path = None
            self.after(0, lambda n=count: self._log(f"Capturadas empilhadas: {n}", "robot"))
            self.after(0, self._refresh_capture_status)
        except Exception as exc:
            self.after(0, lambda e=str(exc): self._log(f"Erro ao salvar contagem da bandeja: {e}", "robot"))
        finally:
            if tmp_path is not None:
                try:
                    tmp_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def _on_connected(self):
        self.lbl_conn.config(text=f"Conectado ({self.port_var.get()})", foreground="#2e7d32")
        self.btn_connect.config(state="normal", text="Desconectar")
        if hasattr(self, "btn_pump"):
            self.btn_pump.config(text="💨 Ventosa", bg="#eceff1", relief="raised")
        self._refresh_capture_status()
        self._log(f"🔗 Braço conectado em {self.port_var.get()}", "robot")

    def _on_conn_fail(self, err: str):
        self.is_connected = False
        self.worker = None
        self.executor = None
        self.lbl_conn.config(text="Falha na conexão", foreground="#d32f2f")
        self.btn_connect.config(state="normal", text="Conectar")
        if hasattr(self, "btn_pump"):
            self.btn_pump.config(text="💨 Ventosa", bg="#eceff1", relief="raised")
        messagebox.showerror("Erro de Conexão", f"Não foi possível conectar:\n{err}")

    def _disconnect(self):
        if self.worker:
            try:
                self.worker.close()
            except Exception:
                pass
        self.worker = None
        self.executor = None
        self.is_connected = False
        self.lbl_conn.config(text="Desconectado", foreground="#d32f2f")
        self.btn_connect.config(text="Conectar")
        if hasattr(self, "btn_pump"):
            self.btn_pump.config(text="💨 Ventosa", bg="#eceff1", relief="raised")
        self._log("🔌 Braço desconectado.", "robot")

    # ─── Reposição de Peças e Movimento Manual do Robô ─────────────────────────

    def _enter_setup_mode(self):
        if self.ai_thinking or self.robot_busy:
            if not messagebox.askyesno("Modo Reposição", "Uma ação está em andamento. Entrar no modo de reposição mesmo assim?"):
                return
        self.mode = "setup"
        self.game_over = False
        self.ai_thinking = False
        self.robot_busy = False
        self.selected_from = None
        self.selected_to = None
        self.valid_dests = set()
        self.last_move_sqs = []

        # Esvazia o tabuleiro para montagem
        self.board_state = BoardState("W:W:B")
        self.lbl_turn.config(
            text="🛠️  MODO REPOR PEÇAS — Tabuleiro Vazio",
            foreground="#0277bd"
        )
        self.lbl_status.config(
            text="Modo Reposição: Selecione as casas e mova o robô para colocar as peças. Quando terminar, clique em 'Habilitar para Jogar'.",
            foreground="#0277bd"
        )
        self.lbl_from.config(text=" —— ")
        self.lbl_to.config(text=" —— ")
        self.lbl_hint.config(text="Clique em qualquer casa para enviar o robô até ela.")
        self.btn_play.config(state="disabled")
        if hasattr(self, "btn_enable_play"):
            self.btn_enable_play.config(state="normal", text="🎮 HABILITAR PARA JOGAR", bg="#2e7d32")

        self._draw_board()
        self._draw_pieces()
        self._refresh_colors()
        self._log("🛠️ Modo Repor Peças ativado (tabuleiro vazio).", "info")

    def _enable_play_mode(self):
        if self.ai_thinking or self.robot_busy:
            return

        # Se o tabuleiro estiver vazio, preenche com as peças da posição inicial
        if not self.board_state.piece_map():
            self.board_state = BoardState(INITIAL_POSITION)

        self.mode = "play"
        self.game_over = False
        self.ai_thinking = False
        self.robot_busy = False
        self.move_count = 0
        self.selected_from = None
        self.selected_to = None
        self.valid_dests = set()
        self.last_move_sqs = []

        # Zera contagem da bandeja de captura
        self._reset_capture_count_silent()

        self.lbl_turn.config(text="▶  Sua vez — clique numa peça BRANCA", foreground="#2e7d32")
        self.lbl_movecount.config(text="Lances: 0")
        self.lbl_hint.config(text="Clique numa peça branca para começar.")
        self.btn_play.config(state="disabled")
        if hasattr(self, "btn_enable_play"):
            self.btn_enable_play.config(state="disabled", text="✔ Jogo Habilitado", bg="#78909c")

        self._draw_board()
        self._draw_pieces()
        self._update_status()
        self._refresh_colors()
        self._log("=== Partida Iniciada ===", "info")
        messagebox.showinfo("Jogo Habilitado", "O tabuleiro está pronto e a partida começou!\nVocê joga com as peças BRANCAS.")

    def _clear_board_for_setup(self):
        self._enter_setup_mode()

    def _fill_initial_pieces(self):
        self.board_state = BoardState(INITIAL_POSITION)
        self._draw_board()
        self._draw_pieces()
        self._refresh_colors()
        self.lbl_hint.config(text="Peças iniciais posicionadas. Clique em 'HABILITAR PARA JOGAR' para começar.")
        self._log("Posição inicial carregada no tabuleiro.", "info")

    def _reset_capture_count(self):
        color = self.arm_color_var.get()
        self.capture_stack_count = 0
        if self.executor:
            self.executor.capture_count = 0
        self._update_capture_stack_count(color, 0)
        self._refresh_capture_status()
        self._log("🗑️ Bandeja de capturas zerada (contagem = 0, Z na altura calibrada).", "robot")
        messagebox.showinfo(
            "Bandeja Zerada",
            "Contagem de peças capturadas zerada com sucesso!\n"
            "A entrega voltará a ser feita exatamente na altura calibrada da bandeja."
        )

    def _reset_capture_count_silent(self):
        color = self.arm_color_var.get()
        self.capture_stack_count = 0
        if self.executor:
            self.executor.capture_count = 0
        self._update_capture_stack_count(color, 0)
        self._refresh_capture_status()

    def _refresh_capture_status(self):
        count = self.capture_stack_count
        arm_cfg = self.config.get("arms", {}).get(self.arm_color_var.get(), {})
        cz = float(arm_cfg.get("capture_z", 24.0))
        step = float(arm_cfg.get("capture_stack_step_mm", 5.0))
        current_z = cz + count * step
        if hasattr(self, "lbl_tray_status"):
            self.lbl_tray_status.config(
                text=f"Bandeja: {count} peças capturadas (Entrega Z = {current_z:.1f} mm)",
                foreground="#2e7d32" if count < 10 else "#e65100"
            )

    def _get_selected_robot_sq(self) -> str:
        text = self.target_sq_var.get() if hasattr(self, "target_sq_var") else ""
        return _parse_sq_display(text)

    def _set_robot_target_sq(self, sq: str):
        if hasattr(self, "target_sq_var"):
            disp = _format_sq_display(sq)
            self.target_sq_var.set(disp)

    def _prev_robot_sq(self):
        cur = self._get_selected_robot_sq()
        pdn = SQUARE_TO_PDN.get(cur, 1)
        prev_pdn = 32 if pdn <= 1 else pdn - 1
        sq = PDN_TO_SQUARE.get(prev_pdn, "a1")
        self._set_robot_target_sq(sq)

    def _next_robot_sq(self):
        cur = self._get_selected_robot_sq()
        pdn = SQUARE_TO_PDN.get(cur, 1)
        next_pdn = 1 if pdn >= 32 else pdn + 1
        sq = PDN_TO_SQUARE.get(next_pdn, "a1")
        self._set_robot_target_sq(sq)

    def _move_robot_to_target_sq(self):
        if not self.is_connected or not self.worker:
            messagebox.showwarning("Aviso", "Conecte o braço robótico (Dobot) antes de mover!")
            return
        if self.robot_busy or self.ai_thinking:
            messagebox.showwarning("Aviso", "O robô já está ocupado executando uma ação. Aguarde a finalização!")
            return

        sq = self._get_selected_robot_sq()
        if not sq or sq not in self.square_coords:
            messagebox.showinfo(
                "Casa sem Coordenada",
                f"A casa {sq.upper()} ainda não possui coordenadas calibradas em config/default.yaml!"
            )
            return

        target = self.square_coords[sq]
        arm_cfg = self.config.get("arms", {}).get(self.arm_color_var.get(), {})
        travel_z = float(arm_cfg.get("travel_z", 80.0))
        safe_z = max(travel_z, float(target["z"]) + 35.0, 60.0)

        self.robot_busy = True
        self.btn_move_to_sq.config(state="disabled")
        self.lbl_status.config(text=f"Robô movendo até a casa {sq.upper()}...", foreground="#1565c0")
        self._log(f"🤖 Movendo até a casa {sq.upper()} (X={target['x']:.1f}, Y={target['y']:.1f}, Z={target['z']:.1f})", "robot")

        def _do_move():
            try:
                # 1. Se estiver baixo, sobe verticalmente primeiro
                cur = self.worker.get_pose()
                if cur[2] < safe_z - 10.0:
                    self.worker.move_to(cur[0], cur[1], safe_z, cur[3], joint=True)
                # 2. Deslocamento na altura segura até sobre a casa
                self.worker.move_to(target["x"], target["y"], safe_z, target.get("r", 0.0), joint=True)
                # 3. Pré-aproximação (18 mm acima da peça)
                z_pre = float(target["z"]) + 18.0
                self.worker.move_to(target["x"], target["y"], z_pre, target.get("r", 0.0), joint=True)
                # 4. Descida vertical final em linha reta (MOVL)
                self.worker.move_to(target["x"], target["y"], target["z"], target.get("r", 0.0), joint=False)
                self.after(0, lambda: self._log(f"✅ Robô posicionado na casa {sq.upper()}", "robot"))
            except Exception as e:
                self.after(0, lambda err=str(e): messagebox.showerror("Erro de Movimento", f"Falha ao mover o robô:\n{err}"))
            finally:
                self.robot_busy = False
                self.after(0, lambda: self.btn_move_to_sq.config(state="normal"))
                self.after(0, self._update_status)

        threading.Thread(target=_do_move, daemon=True).start()

    def _lift_robot_arm(self):
        if not self.is_connected or not self.worker:
            messagebox.showwarning("Aviso", "Conecte o braço robótico (Dobot) antes de mover!")
            return
        if self.robot_busy or self.ai_thinking:
            return

        arm_cfg = self.config.get("arms", {}).get(self.arm_color_var.get(), {})
        travel_z = float(arm_cfg.get("travel_z", 80.0))

        self.robot_busy = True
        self.lbl_status.config(text="Subindo braço para altura segura...", foreground="#1565c0")

        def _do_lift():
            try:
                pose = self.worker.get_pose()
                target_z = max(travel_z, pose[2] + 40.0, 60.0)
                self.worker.move_to(pose[0], pose[1], target_z, pose[3], joint=True)
                self.after(0, lambda: self._log(f"⬆ Braço elevado para Z={target_z:.1f} mm", "robot"))
            except Exception as e:
                self.after(0, lambda err=str(e): messagebox.showerror("Erro", str(err)))
            finally:
                self.robot_busy = False
                self.after(0, self._update_status)

        threading.Thread(target=_do_lift, daemon=True).start()

    def _toggle_suction(self):
        if not self.is_connected or not self.worker:
            messagebox.showwarning("Aviso", "Conecte o braço robótico (Dobot) antes de acionar a ventosa!")
            return
        try:
            new_state = not getattr(self.worker, "sucking", False)
            self.worker.set_suction(new_state)
            if hasattr(self, "btn_pump"):
                self.btn_pump.config(
                    text="💨 Ventosa: ON" if new_state else "💨 Ventosa",
                    bg="#81c784" if new_state else "#eceff1",
                    relief="sunken" if new_state else "raised"
                )
            self._log(f"Ventosa {'LIGADA' if new_state else 'DESLIGADA'}", "robot")
        except Exception as e:
            messagebox.showerror("Erro Ventosa", str(e))

    def _robot_home(self):
        if not self.is_connected or not self.worker:
            messagebox.showwarning("Aviso", "Conecte o braço robótico (Dobot) primeiro!")
            return
        if self.robot_busy or self.ai_thinking:
            return

        self.robot_busy = True
        self.lbl_status.config(text="Robô indo para posição Home...", foreground="#1565c0")

        def _do_home():
            try:
                self.worker.home()
                self.after(0, lambda: self._log("🏠 Braço retornou à posição Home.", "robot"))
            except Exception as e:
                self.after(0, lambda err=str(e): messagebox.showerror("Erro Home", str(err)))
            finally:
                self.robot_busy = False
                self.after(0, self._update_status)

        threading.Thread(target=_do_home, daemon=True).start()

    def _clear_alarms_action(self):
        if not self.is_connected or not self.worker:
            messagebox.showwarning("Aviso", "Conecte o braço robótico (Dobot) primeiro!")
            return
        try:
            self.worker.clear_alarms()
            self.robot_busy = False
            self.lbl_status.config(text="Alarmes limpos! O braço foi destravado com sucesso.", foreground="#2e7d32")
            messagebox.showinfo(
                "Robô Destravado",
                "Os alarmes do Dobot foram limpos e a fila foi reiniciada com sucesso!\n"
                "Você pode continuar o jogo ou reposicionar o braço."
            )
        except Exception as e:
            messagebox.showerror("Erro ao Destravar", f"Falha ao limpar alarmes do robô:\n{e}")

    def _on_close(self):
        if (self.robot_busy or self.ai_thinking):
            if not messagebox.askyesno("Fechar", "Um lance está em progresso. Fechar mesmo assim?"):
                return
        self._disconnect()
        self.destroy()


# ─── Entry Point ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Damas Brasileiras — Humano vs I.A. com braço robótico."
    )
    parser.add_argument("--config", default=None)
    parser.add_argument("--arm", default="white", choices=["white"],
                        help="Braço físico disponível: branco (COM3).")
    args = parser.parse_args()
    app = PlayVsAIGUI(config_path=args.config, arm_color=args.arm)
    app.mainloop()


if __name__ == "__main__":
    main()
