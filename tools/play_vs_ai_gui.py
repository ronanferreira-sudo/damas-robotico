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
    HAS_PYDOBOT = True
except ImportError:
    HAS_PYDOBOT = False
    Pydobot = None
    PTPMode = None

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


# ─── Worker do Dobot ──────────────────────────────────────────────────────────

class DobotWorker:
    def __init__(self, port: str, max_reach=380.0, min_reach=100.0,
                 z_min=-70.0, z_max=160.0):
        if not HAS_PYDOBOT:
            raise ImportError("pydobot não instalado. Execute: pip install pydobot")
        self.bot = Pydobot(port=port)
        self.lock = threading.Lock()
        self.sucking = False
        self.max_reach = max_reach
        self.min_reach = min_reach
        self.z_min = z_min
        self.z_max = z_max

    def get_pose(self):
        with self.lock:
            p = self.bot.pose()
            return (float(p[0]), float(p[1]), float(p[2]), float(p[3]))

    def move_to(self, x, y, z, r=0.0, timeout=10.0):
        dist = math.sqrt(x * x + y * y)
        if dist > self.max_reach:
            raise ValueError(f"Fora do alcance máximo ({dist:.1f} > {self.max_reach:.0f} mm).")
        if dist < self.min_reach:
            raise ValueError(f"Muito próximo da base ({dist:.1f} < {self.min_reach:.0f} mm).")
        if not (self.z_min <= z <= self.z_max):
            raise ValueError(f"Z={z:.1f} fora dos limites [{self.z_min:.0f}, {self.z_max:.0f}] mm.")
        with self.lock:
            res = self.bot._set_ptp_cmd(x, y, z, r, mode=PTPMode.MOVL_XYZ, wait=False)
        if res is None or not getattr(res, "params", None):
            raise TimeoutError("Falha na comunicação com o robô.")
        # O índice da fila Dobot é um uint32 little-endian. `L` depende da
        # plataforma e pode ter 8 bytes, causando erro no Linux.
        if len(res.params) < 4:
            raise TimeoutError("Resposta do Dobot sem índice de comando válido.")
        expected_idx = int.from_bytes(res.params[:4], byteorder="little", signed=False)
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                with self.lock:
                    cur = self.bot._get_queued_cmd_current_index()
                if cur >= expected_idx:
                    return
            except Exception:
                pass
            time.sleep(0.05)
        raise TimeoutError(f"Robô não alcançou ({x:.1f},{y:.1f},{z:.1f}) a tempo.")

    def set_suction(self, enable: bool):
        with self.lock:
            self.sucking = enable
            self.bot.suck(enable)

    def home(self):
        with self.lock:
            self.bot._set_ptp_cmd(227.53, 0.0, 140.83, 0.0,
                                  mode=PTPMode.MOVJ_XYZ, wait=False)

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
        self.travel_z = travel_z
        self.capture_pos = capture_pos
        self.capture_stack_step_mm = max(0.0, float(capture_stack_step_mm))
        self.capture_count = max(0, int(capture_count))
        self.on_capture_count = on_capture_count

    def _coord(self, sq: str):
        c = self.coords.get(sq.lower()) or self.coords.get(sq.upper())
        if not c:
            raise ValueError(f"Casa {sq} não calibrada!")
        return c

    def _above(self, sq: str):
        c = self._coord(sq)
        safe_z = max(self.travel_z, float(c["z"]) + 40.0)
        self.worker.move_to(c["x"], c["y"], safe_z, c.get("r", 0.0))

    def _to_sq(self, sq: str):
        c = self._coord(sq)
        self.worker.move_to(c["x"], c["y"], c["z"], c.get("r", 0.0))

    def pick(self, sq: str):
        self._above(sq); self._to_sq(sq)
        self.worker.set_suction(True); time.sleep(0.5)
        self._above(sq)

    def place(self, sq: str):
        self._above(sq); self._to_sq(sq)
        time.sleep(0.3); self.worker.set_suction(False)
        time.sleep(0.3); self._above(sq)

    def move_piece(self, frm: str, to: str):
        self.pick(frm); self._above(to); self.place(to)

    def remove_captured(self, sq: str):
        if not self.capture_pos:
            raise ValueError(
                "Destino das peças capturadas não calibrado. Use a tela de calibragem "
                "para gravar a bandeja antes de jogar."
            )
        cx, cy, cz = self.capture_pos[:3]
        cr = self.capture_pos[3] if len(self.capture_pos) > 3 else 0.0
        drop_z = cz + self.capture_count * self.capture_stack_step_mm
        if not self.worker.z_min <= drop_z <= self.worker.z_max:
            raise ValueError(
                f"A pilha de capturadas exige Z={drop_z:.1f} mm, fora dos limites do braço. "
                "Reduza a subida Z ou grave a bandeja mais baixa."
            )
        safe_z = min(self.worker.z_max, max(self.travel_z, drop_z + 30.0))
        if safe_z < drop_z + 10.0:
            raise ValueError(
                "Não há altura segura para alcançar o topo da pilha. "
                "Grave a bandeja mais baixa ou reduza a subida Z."
            )
        self.pick(sq)
        self.worker.move_to(cx, cy, safe_z, cr)
        self.worker.move_to(cx, cy, drop_z, cr)
        self.worker.set_suction(False); time.sleep(0.3)
        self.capture_count += 1
        if self.on_capture_count:
            self.on_capture_count(self.capture_count)
        self.worker.move_to(cx, cy, safe_z, cr)

    def execute_actions(self, actions: list, log_fn=None):
        for kind, color, a, b in actions:
            if log_fn:
                log_fn(f"  → {kind}: {a}" + (f" → {b}" if b else ""))
            if kind == "capture":
                self.remove_captured(a)
            else:
                self.move_piece(a, b)


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
        self.board_state = BoardState(INITIAL_POSITION)
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
            text="▶  Sua vez — clique numa peça BRANCA",
            font=("Arial", 11, "bold"),
            foreground="#2e7d32"
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

        self.lbl_hint = ttk.Label(move_panel, text="Clique numa peça branca para começar.",
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

        tk.Button(
            btn_row,
            text="✖ Limpar",
            bg="#546e7a", fg="#ffffff",
            activebackground="#37474f", activeforeground="#ffffff",
            font=("Arial", 10, "bold"),
            relief="raised", pady=5, padx=10,
            command=self._clear_selection,
            cursor="hand2"
        ).pack(side="left", fill="x", expand=True, padx=(0, 4))

        tk.Button(
            btn_row,
            text="🔄 Nova Partida",
            bg="#1565c0", fg="#ffffff",
            activebackground="#0d47a1", activeforeground="#ffffff",
            font=("Arial", 10, "bold"),
            relief="raised", pady=5, padx=10,
            command=self._new_game,
            cursor="hand2"
        ).pack(side="right", fill="x", expand=True, padx=(4, 0))

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

        # Legenda de cores
        leg_fr = ttk.LabelFrame(right, text=" Legenda ", padding=6)
        leg_fr.grid(row=3, column=0, sticky="ew", pady=(0, 6))

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

        # Conexão Dobot
        conn_fr = ttk.LabelFrame(right, text=" Braço Robótico (Dobot) ", padding=8)
        conn_fr.grid(row=4, column=0, sticky="ew", pady=(0, 6))
        conn_fr.columnconfigure(1, weight=1)

        ttk.Label(conn_fr, text="Porta:").grid(row=0, column=0, sticky="w", padx=(0, 4))
        try:
            import serial.tools.list_ports
            ports = [p.device for p in serial.tools.list_ports.comports()] or ["COM5"]
        except Exception:
            ports = ["COM5"]
        self.port_var = tk.StringVar(value=ports[0])
        ttk.Combobox(conn_fr, textvariable=self.port_var, values=ports, width=8).grid(
            row=0, column=1, sticky="ew", padx=(0, 4))
        self.btn_connect = ttk.Button(conn_fr, text="Conectar", command=self._toggle_conn)
        self.btn_connect.grid(row=0, column=2)

        ttk.Label(conn_fr, text="Braço:").grid(row=1, column=0, sticky="w", pady=(4, 0))
        cb_arm = ttk.Combobox(conn_fr, textvariable=self.arm_color_var,
                               values=["white", "black"], state="readonly", width=8)
        cb_arm.grid(row=1, column=1, sticky="ew", pady=(4, 0))
        cb_arm.bind("<<ComboboxSelected>>", lambda e: self._load_coords())

        self.lbl_conn = ttk.Label(conn_fr, text="Desconectado",
                                   foreground="#d32f2f", font=("Arial", 9, "bold"))
        self.lbl_conn.grid(row=2, column=0, columnspan=3, sticky="w", pady=(4, 0))

        self.var_robot = tk.BooleanVar(value=True)
        ttk.Checkbutton(conn_fr, text="Usar braço para executar os lances",
                         variable=self.var_robot).grid(
            row=3, column=0, columnspan=3, sticky="w", pady=(4, 0))

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

        # Casas de origem do jogador da vez (para destacar com borda)
        is_human_turn = (self.board_state.turn_name == self.human_color
                         and not self.game_over and not self.ai_thinking)
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
        pm = self.board_state.piece_map()

        for sq in DRAUGHTS_SQUARES:
            # Cor base
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
        if self.game_over or self.ai_thinking or self.robot_busy:
            return
        if self.board_state.turn_name != self.human_color:
            return

        sq = self._xy_to_sq(event.x, event.y)
        if sq is None or not self._is_playable(sq):
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
                self.after(0, lambda e=str(exc): messagebox.showerror("Erro", e))
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

        if self.board_state.is_game_over():
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
        msg = f"A I.A. perdeu por erro durante a jogada.\n\n{reason}"
        self.lbl_turn.config(text="I.A. perdeu por erro", foreground="#2e7d32")
        self.lbl_status.config(text="Vitória do jogador — erro da I.A.", foreground="#2e7d32")
        self._set_locked(False)
        self._log(msg, "win")
        messagebox.showerror("Vitória do jogador", msg)

    def _after_ai(self):
        self.ai_thinking = False
        self._refresh_colors()
        self._draw_pieces()
        self._update_movecount()
        self._set_locked(False)

        if self.board_state.is_game_over():
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

    def _announce_winner(self):
        self.game_over = True
        outcome = self.board_state.outcome()
        if outcome == "white":
            msg = "AS BRANCAS VENCERAM! Parabéns!"
            fg = "#2e7d32"
        elif outcome == "black":
            msg = "🤖 AS PRETAS (I.A.) VENCERAM!"
            fg = "#c62828"
        else:
            msg = "EMPATE!"
            fg = "#e65100"
        self.lbl_turn.config(text=msg, foreground=fg)
        self.lbl_status.config(text=msg, foreground=fg)
        self._log(f"\n{'='*28}", "info")
        self._log(msg, "win")
        self._log(f"{'='*28}", "info")
        messagebox.showinfo("Fim de Jogo", msg)

    def _new_game(self):
        if self.ai_thinking or self.robot_busy:
            if not messagebox.askyesno("Nova partida",
                                        "Um lance está em progresso. Deseja reiniciar mesmo assim?"):
                return
        self.board_state = BoardState(INITIAL_POSITION)
        self.selected_from = None
        self.selected_to = None
        self.valid_dests = set()
        self.last_move_sqs = []
        self.game_over = False
        self.ai_thinking = False
        self.robot_busy = False
        self.move_count = 0

        self.lbl_from.config(text=" —— ")
        self.lbl_to.config(text=" —— ")
        self.lbl_hint.config(text="Clique numa peça branca para começar.")
        self.btn_play.config(state="disabled")
        self.lbl_turn.config(text="▶  Sua vez — clique numa peça BRANCA", foreground="#2e7d32")
        self.lbl_movecount.config(text="Lances: 0")

        self._draw_board()
        self._draw_pieces()
        self._update_status()
        self._log("=== Nova Partida ===", "info")
        self._log("Você joga com as BRANCAS.", "white")
        self._log("I.A. joga com as PRETAS.", "black")

    # ─── Log ──────────────────────────────────────────────────────────────────

    def _log(self, msg: str, tag: str = "info"):
        # Os detalhes ficam fora da interface; status e avisos seguem visíveis.
        return

    # ─── Conexão Dobot ────────────────────────────────────────────────────────

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
        self._log(f"🔗 Braço conectado em {self.port_var.get()}", "robot")

    def _on_conn_fail(self, err: str):
        self.is_connected = False
        self.worker = None
        self.executor = None
        self.lbl_conn.config(text="Falha na conexão", foreground="#d32f2f")
        self.btn_connect.config(state="normal", text="Conectar")
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
        self._log("🔌 Braço desconectado.", "robot")

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
    parser.add_argument("--arm", default="white", choices=["white", "black"])
    args = parser.parse_args()
    app = PlayVsAIGUI(config_path=args.config, arm_color=args.arm)
    app.mainloop()


if __name__ == "__main__":
    main()
