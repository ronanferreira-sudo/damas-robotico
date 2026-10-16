"""Interface Gráfica (GUI) para Calibração Manual das 32 Casas de Damas.

Permite:
- Visualizar o tabuleiro de Damas 8x8 com as 32 casas jogáveis (PDN 1 a 32).
- Mover o braço robótico com a mão (segurando o botão físico de destravamento do Dobot)
  ou através dos botões de Jog (+X, -X, +Y, -Y, +Z, -Z).
- Leitura contínua em tempo real da posição (X, Y, Z).
- Gravar as coordenadas de cada uma das 32 casas com um clique (ou auto-avanço).
- Testar a posição de qualquer casa enviando o braço até ela (com timeout de segurança).
- Testar a bomba de sucção (On/Off).
- Botão para limpar todas as casas e começar do zero.
- Salvar tudo diretamente em config/default.yaml com validação de erros.

Uso:
    python tools/arm_setup_draughts_gui.py
"""

from __future__ import annotations

import math
import os
import struct
import sys
import tempfile
import threading
import time
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "default.yaml"

# ─── Pydobot Import ───────────────────────────────────────────────────────────

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


def find_dobot_ports() -> list[str]:
    # Este setup usa um único Dobot, conectado à COM3.
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
    for common in ("COM3",):
        if common not in result:
            result.append(common)
    return result


# ─── Mapeamento de Casas de Damas Brasileiras ─────────────────────────────────

PDN_TO_SQUARE: dict[int, str] = {}
SQUARE_TO_PDN: dict[str, int] = {}
DRAUGHTS_SQUARES: list[str] = []

_pdn = 1
for _rank in range(1, 9):
    for _file_idx in range(8):
        _col = chr(ord('a') + _file_idx)
        _sq = f"{_col}{_rank}"
        if (_file_idx + _rank) % 2 == 1:
            DRAUGHTS_SQUARES.append(_sq)
            PDN_TO_SQUARE[_pdn] = _sq
            SQUARE_TO_PDN[_sq] = _pdn
            _pdn += 1


# ─── Thread Segura do Dobot com Proteção de Alcance ───────────────────────────

class DobotWorker:
    """Gerencia comunicação serial com o Dobot com proteção contra travamentos."""

    def __init__(
        self,
        port: str,
        max_reach: float = 380.0,
        min_reach: float = 100.0,
        z_min: float = -70.0,
        z_max: float = 160.0,
    ):
        if not HAS_PYDOBOT:
            raise ImportError("pydobot não instalado! Instale com: pip install pydobot")
        self.bot = Pydobot(port=port)
        self.lock = threading.Lock()
        self.sucking = False
        self.max_reach = max_reach
        self.min_reach = min_reach
        self.z_min = z_min
        self.z_max = z_max

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

    def get_pose(self) -> tuple[float, float, float, float]:
        with self.lock:
            p = self.bot.pose()
            return (float(p[0]), float(p[1]), float(p[2]), float(p[3]))

    def move_to(self, x: float, y: float, z: float, r: float = 0.0,
                timeout: float = 12.0, joint: bool = False):
        """Move o braço para (x, y, z, r) com espera real de parada física."""
        dist = math.sqrt(x * x + y * y)
        if dist > self.max_reach:
            raise ValueError(
                f"Posição fora do alcance máximo do braço!\n"
                f"Raio atual: {dist:.1f} mm (máximo permitido: {self.max_reach:.0f} mm).\n"
                f"Aproxime o tabuleiro da base do robô."
            )
        if dist < self.min_reach:
            raise ValueError(
                f"Posição muito próxima da base do braço!\n"
                f"Raio atual: {dist:.1f} mm (mínimo: {self.min_reach:.0f} mm)."
            )
        if z < self.z_min or z > self.z_max:
            raise ValueError(
                f"Altura Z={z:.1f} mm fora dos limites seguros do robô "
                f"({self.z_min:.0f} a {self.z_max:.0f} mm)!"
            )

        ptp_mode = PTPMode.MOVJ_XYZ if joint else PTPMode.MOVL_XYZ
        with self.lock:
            res = self.bot._set_ptp_cmd(x, y, z, r, mode=ptp_mode, wait=False)
        if res is None or not getattr(res, 'params', None):
            self.clear_alarms()
            raise TimeoutError(f"Falha na comunicação com o robô ao mover para (X={x:.1f}, Y={y:.1f}, Z={z:.1f}).\nVerifique a conexão USB do Dobot.")
        expected_idx = struct.unpack_from('L', res.params, 0)[0]

        start_t = time.time()
        while time.time() - start_t < timeout:
            try:
                with self.lock:
                    current_idx = self.bot._get_queued_cmd_current_index()
                if current_idx >= expected_idx:
                    break
            except Exception:
                pass
            time.sleep(0.04)
        else:
            self.clear_alarms()
            raise TimeoutError(f"O robô não conseguiu alcançar a posição (X={x:.1f}, Y={y:.1f}, Z={z:.1f}) a tempo.\nVerifique se o braço está no limite da articulação física.")

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

    def home(self):
        with self.lock:
            self.bot._set_ptp_cmd(227.53, 0.0, 140.83, 0.0, mode=PTPMode.MOVJ_XYZ, wait=False)

    def toggle_suction(self) -> bool:
        with self.lock:
            self.sucking = not self.sucking
            self.bot.suck(self.sucking)
            return self.sucking

    def set_suction(self, enable: bool):
        with self.lock:
            self.sucking = enable
            self.bot.suck(enable)

    def close(self):
        try:
            with self.lock:
                self.bot.suck(False)
                self.bot.close()
        except Exception:
            pass


# ─── Aplicação Principal (GUI) ────────────────────────────────────────────────

class DraughtsCalibrationGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Calibração das 32 Casas de Damas - Dobot Magician Lite")
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        window_width = min(1080, max(900, screen_width - 40))
        window_height = min(760, max(600, screen_height - 100))
        self.geometry(f"{window_width}x{window_height}+20+20")
        self.minsize(min(900, window_width), min(600, window_height))

        self.worker: DobotWorker | None = None
        self.current_pose = [0.0, 0.0, 0.0, 0.0]
        self.is_connected = False
        self.running = True

        self.selected_sq = tk.StringVar(value="a1")
        self.step_size = tk.DoubleVar(value=5.0)
        self.rotation_step = tk.DoubleVar(value=5.0)
        self.arm_color = tk.StringVar(value="white")
        self.auto_advance = tk.BooleanVar(value=True)
        self.capture_stack_step_var = tk.StringVar(value="5.0")

        self.config = self.load_config()
        self.squares_coords: dict[str, dict[str, float]] = {}
        self.load_coords_from_config()

        self._build_ui()
        self.after(200, self._poll_robot_pose)

    def load_config(self) -> dict:
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        return {}

    def save_config(self):
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=CONFIG_PATH.parent,
                prefix=f"{CONFIG_PATH.stem}_", suffix=".tmp", delete=False,
            ) as tmp_file:
                tmp_path = Path(tmp_file.name)
                yaml.safe_dump(
                    self.config, tmp_file, sort_keys=False,
                    default_flow_style=False, allow_unicode=True,
                )
                tmp_file.flush()
                os.fsync(tmp_file.fileno())

            with tmp_path.open("r", encoding="utf-8") as check_file:
                saved = yaml.safe_load(check_file) or {}
            if saved != self.config:
                raise OSError("A verificação do arquivo salvo não corresponde à configuração atual.")

            os.replace(tmp_path, CONFIG_PATH)
            tmp_path = None
        finally:
            if tmp_path is not None:
                try:
                    tmp_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def load_coords_from_config(self):
        color = self.arm_color.get()
        arm_cfg = self.config.get("arms", {}).get(color, {})

        overrides = arm_cfg.get("square_overrides") or {}
        for sq, pt in overrides.items():
            if isinstance(pt, dict) and "x" in pt and "y" in pt and "z" in pt:
                self.squares_coords[sq.lower()] = {
                    "x": float(pt["x"]), "y": float(pt["y"]), "z": float(pt["z"]),
                    "r": float(pt.get("r", 0.0)),
                }

        corners = arm_cfg.get("corners", {})
        for sq, pt in corners.items():
            if isinstance(pt, dict) and "x" in pt and "y" in pt and "z" in pt:
                sq_lower = sq.lower()
                if sq_lower not in self.squares_coords:
                    self.squares_coords[sq_lower] = {
                        "x": float(pt["x"]), "y": float(pt["y"]), "z": float(pt["z"]),
                        "r": float(pt.get("r", 0.0)),
                    }

    def _save_single_coord(self, sq: str, pt: dict[str, float]) -> bool:
        """Persiste uma única coordenada no arquivo YAML sem reescrever as demais."""
        try:
            color = self.arm_color.get()
            arm_cfg = self.config.setdefault("arms", {}).setdefault(color, {})
            arm_cfg.setdefault("square_overrides", {})[sq.upper()] = {
                "x": float(round(pt["x"], 2)),
                "y": float(round(pt["y"], 2)),
                "z": float(round(pt["z"], 2)),
                "r": float(round(pt.get("r", 0.0), 2)),
            }
            self.save_config()
            return True
        except Exception as exc:
            messagebox.showerror("Erro ao Salvar", f"Falha ao salvar a casa {sq.upper()}:\n{exc}")
            return False

    def _build_ui(self):
        style = ttk.Style(self)
        style.theme_use("clam")

        main_frame = ttk.Frame(self, padding=10)
        main_frame.pack(fill="both", expand=True)

        # ─── Coluna Esquerda: Tabuleiro 8x8 ──────────────────────────────────
        left_col = ttk.Frame(main_frame, padding=4)
        left_col.pack(side="left", fill="both", expand=True, padx=(0, 10))

        board_container = ttk.Frame(left_col)
        board_container.pack(fill="both", expand=True)

        self.sq_buttons: dict[str, tk.Button] = {}

        # 8 fileiras: rank 8 no topo até rank 1 na base
        for rank in range(8, 0, -1):
            row_frame = ttk.Frame(board_container)
            row_frame.pack(fill="both", expand=True)

            ttk.Label(row_frame, text=f"{rank}", width=2, font=("Arial", 9, "bold")).pack(side="left")

            for file_idx in range(8):
                col_char = chr(ord('a') + file_idx)
                sq = f"{col_char}{rank}"
                is_playable = (file_idx + rank) % 2 == 1

                if is_playable:
                    pdn_num = SQUARE_TO_PDN[sq]
                    has_coord = sq in self.squares_coords
                    bg_color = "#2e7d32" if has_coord else "#37474f"
                    text = f"{pdn_num}\n{sq.upper()}"

                    btn = tk.Button(
                        row_frame,
                        text=text,
                        bg=bg_color,
                        fg="#ffffff",
                        activebackground="#1565c0",
                        activeforeground="#ffffff",
                        font=("Arial", 9, "bold"),
                        relief="ridge",
                        command=lambda s=sq: self.on_select_square(s),
                        cursor="hand2"
                    )
                    btn.pack(side="left", fill="both", expand=True, padx=2, pady=2)
                    self.sq_buttons[sq] = btn
                else:
                    btn_blank = tk.Label(
                        row_frame,
                        text="",
                        bg="#eceff1",
                        relief="flat"
                    )
                    btn_blank.pack(side="left", fill="both", expand=True, padx=2, pady=2)

        # Indicador de colunas (a..h)
        cols_frame = ttk.Frame(board_container)
        cols_frame.pack(fill="x", pady=(4, 0))
        ttk.Label(cols_frame, text="", width=2).pack(side="left")
        for file_idx in range(8):
            col_char = chr(ord('a') + file_idx)
            ttk.Label(cols_frame, text=col_char, font=("Arial", 9, "bold")).pack(side="left", fill="x", expand=True)

        # Barra de status do tabuleiro e botões utilitários
        board_actions = ttk.Frame(left_col)
        board_actions.pack(fill="x", pady=(10, 0))
        self.lbl_calib_count = ttk.Label(board_actions, text="")  # estado interno, sem ocupar a tela

        btn_clear = tk.Button(
            board_actions,
            text="LIMPAR TUDO",
            bg="#d32f2f",
            fg="#ffffff",
            activebackground="#b71c1c",
            activeforeground="#ffffff",
            font=("Arial", 9, "bold"),
            relief="raised",
            command=self.clear_all_coords,
            cursor="hand2",
            padx=8
        )
        btn_clear.pack(side="right")

        btn_save_config = tk.Button(
            board_actions,
            text="SALVAR NO SISTEMA",
            bg="#0d47a1",
            fg="#ffffff",
            activebackground="#002171",
            font=("Arial", 9, "bold"),
            relief="raised",
            command=self.save_all_to_config,
            cursor="hand2",
            padx=8,
        )
        btn_save_config.pack(side="right", padx=(0, 6))

        # ─── Coluna Direita: Controles e Jog ──────────────────────────────────
        right_col = ttk.Frame(main_frame, width=400)
        right_col.pack(side="right", fill="both", expand=False)

        # 1. Conexão
        conn_frame = ttk.LabelFrame(right_col, text=" Conexão com Dobot ", padding=8)
        conn_frame.pack(fill="x", pady=(0, 6))

        ports = find_dobot_ports()
        self.port_var = tk.StringVar(value=ports[0])

        row_c = ttk.Frame(conn_frame)
        row_c.pack(fill="x")
        ttk.Label(row_c, text="Porta:").pack(side="left", padx=(0, 4))
        self.combo_port = ttk.Combobox(row_c, textvariable=self.port_var, values=ports, width=8)
        self.combo_port.pack(side="left", padx=(0, 2))
        ttk.Button(row_c, text="🔄", width=3, command=self._refresh_ports).pack(side="left", padx=(0, 6))

        ttk.Label(row_c, text="Braço:").pack(side="left", padx=(0, 4))
        self.combo_arm = ttk.Combobox(
            row_c,
            textvariable=self.arm_color,
            values=["white"],
            width=8,
            state="disabled"
        )
        self.combo_arm.pack(side="left", padx=(0, 6))
        self.combo_arm.bind("<<ComboboxSelected>>", lambda e: self._on_arm_color_changed())

        self.btn_connect = ttk.Button(row_c, text="Conectar", command=self.toggle_connection)
        self.btn_connect.pack(side="right")

        self.lbl_conn_status = ttk.Label(conn_frame, text="Desconectado", foreground="#d32f2f")

        # 2. Posição Atual (Real-Time)
        pos_frame = ttk.Frame(right_col, padding=(0, 2))
        pos_frame.pack(fill="x", pady=(0, 6))

        self.lbl_pos_display = ttk.Label(
            pos_frame,
            text="X: 0.00 mm   Y: 0.00 mm   Z: 0.00 mm   R: 0.00°",
            font=("Consolas", 10, "bold"),
            foreground="#0d47a1"
        )
        self.lbl_pos_display.pack(anchor="center", pady=4)


        # 3. Gravação da Casa Ativa
        record_frame = ttk.Frame(right_col, padding=0)
        record_frame.pack(fill="x", pady=(0, 6))

        self.lbl_active_sq = ttk.Label(record_frame, text="")
        self.lbl_sq_saved_pos = ttk.Label(record_frame, text="")

        btn_record = tk.Button(
            record_frame,
            text="GRAVAR POSIÇÃO",
            bg="#2e7d32",
            fg="#ffffff",
            activebackground="#1b5e20",
            font=("Arial", 10, "bold"),
            relief="raised",
            command=self.record_current_to_selected,
            cursor="hand2",
            pady=4
        )
        btn_record.pack(fill="x", pady=(0, 6))

        row_acts = ttk.Frame(record_frame)
        row_acts.pack(fill="x")

        self.btn_go_to_sq = ttk.Button(
            row_acts,
            text="MOVER ROBÔ ATÉ A CASA",
            command=self.move_robot_to_selected
        )
        self.btn_go_to_sq.pack(side="left", fill="x", expand=True, padx=(0, 4))

        self.btn_unlock = tk.Button(
            record_frame,
            text="🚨 DESTRAVAR ROBÔ (LIMPAR ALARME)",
            bg="#d32f2f",
            fg="#ffffff",
            activebackground="#b71c1c",
            font=("Arial", 9, "bold"),
            relief="raised",
            command=self.clear_alarms_action,
            cursor="hand2",
            pady=3,
        )
        self.btn_unlock.pack(fill="x", pady=(4, 0))

        chk_advance = ttk.Checkbutton(record_frame, variable=self.auto_advance)

        # Controles compactos da bandeja de captura, ainda usados pelo jogo.
        capture_frame = ttk.Frame(right_col, padding=(0, 2))
        capture_frame.pack(fill="x", pady=(0, 6))
        self.capture_coord_var = tk.StringVar(value="Bandeja não calibrada")
        self.capture_stack_count_var = tk.StringVar(value="Peças empilhadas: 0")
        ttk.Button(
            capture_frame,
            text="GRAVAR DESTINO DAS CAPTURADAS",
            command=self.record_capture_tray,
        ).pack(fill="x")
        stack_row = ttk.Frame(capture_frame)
        stack_row.pack(fill="x", pady=(4, 0))
        ttk.Label(stack_row, text="Z por peça (mm):").pack(side="left")
        ttk.Spinbox(
            stack_row, from_=0.0, to=20.0, increment=0.5, width=6,
            textvariable=self.capture_stack_step_var,
        ).pack(side="right")
        ttk.Button(
            capture_frame,
            text="ZERAR BANDEJA",
            command=self.reset_capture_stack_count,
        ).pack(fill="x", pady=(4, 0))
        self._refresh_capture_status()

        # 4. Movimentação Manual (Jog)
        jog_frame = ttk.LabelFrame(right_col, text=" Movimentação Manual (Jog) ", padding=8)
        jog_frame.pack(before=record_frame, fill="x", pady=(0, 6))

        row_step = ttk.Frame(jog_frame)
        row_step.pack(fill="x", pady=(0, 6))
        ttk.Label(row_step, text="Passo:").pack(side="left")
        for val in [1.0, 5.0, 10.0, 20.0]:
            ttk.Radiobutton(
                row_step,
                text=f"{int(val)}mm",
                value=val,
                variable=self.step_size
            ).pack(side="left", padx=4)
        ttk.Label(row_step, text="Passo R:").pack(side="left", padx=(8, 2))
        ttk.Spinbox(row_step, from_=1, to=90, increment=1, width=4,
                    textvariable=self.rotation_step).pack(side="left")
        ttk.Label(row_step, text="°").pack(side="left")

        jog_grid = ttk.Frame(jog_frame)
        jog_grid.pack(anchor="center")

        ttk.Button(jog_grid, text="+Y (Frente)", width=12, command=lambda: self.jog(0, 1, 0)).grid(row=0, column=1, padx=2, pady=2)
        ttk.Button(jog_grid, text="+Z (Sobe)", width=10, command=lambda: self.jog(0, 0, 1)).grid(row=0, column=3, padx=(10, 2), pady=2)

        ttk.Button(jog_grid, text="-X (Esq)", width=10, command=lambda: self.jog(-1, 0, 0)).grid(row=1, column=0, padx=2, pady=2)
        ttk.Button(jog_grid, text="HOME", width=12, command=self.robot_home).grid(row=1, column=1, padx=2, pady=2)
        ttk.Button(jog_grid, text="+X (Dir)", width=10, command=lambda: self.jog(1, 0, 0)).grid(row=1, column=2, padx=2, pady=2)

        self.btn_pump = tk.Button(
            jog_grid,
            text="💨 Ventosa",
            bg="#eceff1",
            activebackground="#b0bec5",
            font=("Arial", 9, "bold"),
            width=10,
            command=self.toggle_pump
        )
        self.btn_pump.grid(row=1, column=3, padx=(10, 2), pady=2)

        ttk.Button(jog_grid, text="-Y (Trás)", width=12, command=lambda: self.jog(0, -1, 0)).grid(row=2, column=1, padx=2, pady=2)
        ttk.Button(jog_grid, text="-Z (Desce)", width=10, command=lambda: self.jog(0, 0, -1)).grid(row=2, column=3, padx=(10, 2), pady=2)
        ttk.Button(jog_grid, text="-R", width=10, command=lambda: self.jog(0, 0, 0, -1)).grid(row=3, column=1, padx=2, pady=2)
        ttk.Button(jog_grid, text="+R", width=10, command=lambda: self.jog(0, 0, 0, 1)).grid(row=3, column=2, padx=2, pady=2)

        self.on_select_square("a1")

    # ─── Conexão e Polling ────────────────────────────────────────────────────

    def _refresh_ports(self):
        ports = find_dobot_ports()
        if hasattr(self, "combo_port"):
            self.combo_port.config(values=ports)
            if self.port_var.get() not in ports and ports:
                self.port_var.set(ports[0])

    def toggle_connection(self):
        if self.is_connected:
            self.disconnect_robot()
        else:
            self.connect_robot()

    def connect_robot(self):
        port = self.port_var.get().strip()
        self.lbl_conn_status.config(text="Conectando...", foreground="#e65100")
        self.btn_connect.config(state="disabled")
        self.update_idletasks()

        arm_cfg = self.config.get("arms", {}).get(self.arm_color.get(), {})
        limits_cfg = arm_cfg.get("limits", {})

        def _do_connect():
            try:
                worker = DobotWorker(
                    port,
                    max_reach=float(limits_cfg.get("max_reach_mm", 380.0)),
                    min_reach=float(limits_cfg.get("min_reach_mm", 100.0)),
                    z_min=float(limits_cfg.get("z_min_mm", -70.0)),
                    z_max=float(limits_cfg.get("z_max_mm", 160.0)),
                )
                self.worker = worker
                self.is_connected = True
                self.after(0, self._on_connected_ok)
            except Exception as e:
                err_msg = str(e)
                self.after(0, lambda: self._on_connect_failed(err_msg))

        threading.Thread(target=_do_connect, daemon=True).start()

    def _on_connected_ok(self):
        self.lbl_conn_status.config(text=f"Conectado ({self.port_var.get()})", foreground="#2e7d32")
        self.btn_connect.config(state="normal", text="Desconectar")

    def _on_connect_failed(self, err: str):
        self.is_connected = False
        self.worker = None
        self.lbl_conn_status.config(text="Falha na conexão", foreground="#d32f2f")
        self.btn_connect.config(state="normal", text="Conectar")
        messagebox.showerror("Erro de Conexão", f"Não foi possível conectar ao Dobot:\n{err}")

    def disconnect_robot(self):
        if self.worker:
            self.worker.close()
            self.worker = None
        self.is_connected = False
        self.lbl_conn_status.config(text="Desconectado", foreground="#d32f2f")
        self.btn_connect.config(text="Conectar")
        self.btn_pump.config(bg="#eceff1", text="💨 Ventosa")

    def _poll_robot_pose(self):
        if not self.running:
            return

        if self.is_connected and self.worker:
            def _read():
                try:
                    pose = self.worker.get_pose()
                    self.after(0, lambda: self._update_pose_ui(pose))
                except Exception:
                    pass

            threading.Thread(target=_read, daemon=True).start()

        self.after(200, self._poll_robot_pose)

    def _update_pose_ui(self, pose):
        self.current_pose = [float(pose[0]), float(pose[1]), float(pose[2]), float(pose[3])]
        self.lbl_pos_display.config(
            text=f"X: {self.current_pose[0]:>6.2f} mm   Y: {self.current_pose[1]:>6.2f} mm   Z: {self.current_pose[2]:>6.2f} mm   R: {self.current_pose[3]:>6.2f}°"
        )

    # ─── Ações de Movimento ───────────────────────────────────────────────────

    def clear_alarms_action(self):
        if not self.is_connected or not self.worker:
            messagebox.showwarning("Aviso", "Conecte o Dobot antes de destravar!")
            return
        try:
            self.worker.clear_alarms()
            messagebox.showinfo("Sucesso", "Alarmes do Dobot limpos e comandos destravados com sucesso!")
        except Exception as e:
            messagebox.showerror("Erro ao Destravar", str(e))

    def jog(self, dx: int, dy: int, dz: int, dr: int = 0):
        if not self.is_connected or not self.worker:
            messagebox.showwarning("Aviso", "Conecte o Dobot antes de movimentar!")
            return

        step = self.step_size.get()
        nx = self.current_pose[0] + (dx * step)
        ny = self.current_pose[1] + (dy * step)
        nz = self.current_pose[2] + (dz * step)
        nr = self.current_pose[3] + (dr * self.rotation_step.get())

        def _do_jog():
            try:
                self.worker.move_to(nx, ny, nz, nr)
            except Exception as e:
                self.after(0, lambda err=str(e): messagebox.showwarning("Aviso de Movimento", err))

        threading.Thread(target=_do_jog, daemon=True).start()

    def robot_home(self):
        if not self.is_connected or not self.worker:
            return
        threading.Thread(target=self.worker.home, daemon=True).start()

    def toggle_pump(self):
        if not self.is_connected or not self.worker:
            return
        sucking = self.worker.toggle_suction()
        if sucking:
            self.btn_pump.config(bg="#4caf50", fg="#ffffff", text="💨 LIGADA")
        else:
            self.btn_pump.config(bg="#eceff1", fg="#000000", text="💨 Ventosa")

    # ─── Gerenciamento de Casas ───────────────────────────────────────────────

    def _on_arm_color_changed(self):
        self.squares_coords.clear()
        self.load_coords_from_config()
        self._refresh_capture_status()
        for sq, btn in self.sq_buttons.items():
            btn.config(bg="#2e7d32" if sq in self.squares_coords else "#37474f")
        self.lbl_calib_count.config(text=f"Casas gravadas: {len(self.squares_coords)} / 32")
        self.on_select_square(self.selected_sq.get())

    def on_select_square(self, sq: str):
        self.selected_sq.set(sq)
        pdn = SQUARE_TO_PDN.get(sq, 0)
        self.lbl_active_sq.config(text=f"Casa Selecionada: PDN {pdn} ({sq.upper()})")

        for s, btn in self.sq_buttons.items():
            if s == sq:
                btn.config(relief="solid", bd=3)
            else:
                btn.config(relief="ridge", bd=1)

        if sq in self.squares_coords:
            c = self.squares_coords[sq]
            self.lbl_sq_saved_pos.config(
                text=f"Coordenada salva: X={c['x']:.2f}  Y={c['y']:.2f}  Z={c['z']:.2f}  R={c.get('r', 0.0):.2f}°",
                foreground="#2e7d32"
            )
        else:
            self.lbl_sq_saved_pos.config(text="Coordenada salva: Não gravada", foreground="#d32f2f")

    def record_current_to_selected(self):
        if not self.is_connected:
            messagebox.showwarning("Aviso", "Conecte o Dobot para capturar as coordenadas!")
            return

        x, y, z, r = self.current_pose
        if abs(x) < 1.0 and abs(y) < 1.0:
            messagebox.showwarning("Aviso", "Aguarde a leitura inicial da posição do braço!")
            return

        sq = self.selected_sq.get()
        pdn = SQUARE_TO_PDN.get(sq, 0)

        self.squares_coords[sq] = {"x": round(x, 2), "y": round(y, 2), "z": round(z, 2), "r": round(r, 2)}

        if sq in self.sq_buttons:
            self.sq_buttons[sq].config(bg="#2e7d32")

        self.lbl_calib_count.config(text=f"Casas gravadas: {len(self.squares_coords)} / 32")
        self.on_select_square(sq)

        if self._save_single_coord(sq, self.squares_coords[sq]):
            messagebox.showinfo("Sucesso", f"Coordenada da casa {sq.upper()} gravada e salva no arquivo!")

        if self.auto_advance.get() and pdn < 32:
            next_pdn = pdn + 1
            next_sq = PDN_TO_SQUARE[next_pdn]
            self.after(100, lambda: self.on_select_square(next_sq))

    def move_robot_to_selected(self):
        if not self.is_connected or not self.worker:
            messagebox.showwarning("Aviso", "Conecte o Dobot antes de mover!")
            return

        sq = self.selected_sq.get()
        if sq not in self.squares_coords:
            messagebox.showinfo("Casa sem Coordenada", f"A casa {sq.upper()} ainda não foi calibrada!")
            return

        target = self.squares_coords[sq]
        safe_z = max(float(target["z"]) + 35.0, 60.0)

        # Usa MOVJ (por juntas) para todos os movimentos nessa região:
        # - Deslocamento até a altura segura
        # - Descida final sobre a casa
        # O MOVJ é mais robusto em todo o workspace do Dobot (evita singularidades
        # que o MOVL enfrenta nas casas do rank 1 e 2, perto da base do robô).
        # O ponto final é atingido com a mesma precisão — só o caminho difere.
        def _do_move():
            try:
                # 1. Se estiver baixo, sobe verticalmente primeiro antes de navegar na horizontal
                cur_pose = self.worker.get_pose()
                if cur_pose[2] < safe_z - 10.0:
                    self.worker.move_to(cur_pose[0], cur_pose[1], safe_z, cur_pose[3], joint=True)
                # 2. Deslocamento na altura segura até a casa
                self.worker.move_to(target["x"], target["y"], safe_z, target.get("r", 0.0), joint=True)
                # 3. Descida final sobre a casa
                self.worker.move_to(target["x"], target["y"], target["z"], target.get("r", 0.0), joint=True)
            except Exception as e:
                self.after(0, lambda err=str(e): messagebox.showerror("Erro de Movimento", err))

        threading.Thread(target=_do_move, daemon=True).start()

    def clear_all_coords(self):
        """Apaga todas as coordenadas da memória e do arquivo para começar do zero."""
        if not messagebox.askyesno("Confirmar", "Deseja realmente apagar todas as coordenadas salvas e começar do zero?"):
            return

        self.squares_coords.clear()
        for sq, btn in self.sq_buttons.items():
            btn.config(bg="#37474f")

        self.lbl_calib_count.config(text="Casas gravadas: 0 / 32")
        self.on_select_square(self.selected_sq.get())

        color = self.arm_color.get()
        arm_cfg = self.config.setdefault("arms", {}).setdefault(color, {})
        arm_cfg["corners"] = {}
        arm_cfg["square_overrides"] = {}
        self.save_config()

        messagebox.showinfo("Sucesso", "Todas as coordenadas foram apagadas!\nVocê pode começar a calibrar do zero com o tabuleiro na nova posição.")

    def record_capture_tray(self):
        if not self.is_connected:
            messagebox.showwarning("Aviso", "Conecte o Dobot para capturar a bandeja!")
            return

        color = self.arm_color.get()
        x, y, z, r = self.current_pose
        if abs(x) < 1.0 and abs(y) < 1.0:
            messagebox.showwarning("Aviso", "Aguarde a leitura da posição atual do Dobot.")
            return
        try:
            stack_step = float(self.capture_stack_step_var.get())
            if not 0.0 <= stack_step <= 20.0:
                raise ValueError
        except ValueError:
            messagebox.showwarning("Valor inválido", "A subida Z deve ficar entre 0 e 20 mm.")
            return
        arm_cfg = self.config.setdefault("arms", {}).setdefault(color, {})
        previous = {
            key: arm_cfg.get(key)
            for key in ("capture_x", "capture_y", "capture_z", "capture_r", "capture_stack_step_mm")
        }
        arm_cfg["capture_x"] = float(round(x, 2))
        arm_cfg["capture_y"] = float(round(y, 2))
        arm_cfg["capture_z"] = float(round(z, 2))
        arm_cfg["capture_r"] = float(round(r, 2))
        arm_cfg["capture_stack_step_mm"] = stack_step
        try:
            self.save_config()
            with CONFIG_PATH.open("r", encoding="utf-8") as saved_file:
                saved_config = yaml.safe_load(saved_file) or {}
            saved_arm = saved_config.get("arms", {}).get(color, {})
            saved_position = tuple(saved_arm.get(f"capture_{axis}", 0.0) for axis in "xyzr")
            expected_position = tuple(arm_cfg.get(f"capture_{axis}", 0.0) for axis in "xyzr")
            if saved_position != expected_position:
                raise OSError("A posição da bandeja não foi confirmada no arquivo salvo.")
        except Exception as exc:
            for key, value in previous.items():
                if value is None:
                    arm_cfg.pop(key, None)
                else:
                    arm_cfg[key] = value
            messagebox.showerror(
                "Erro ao salvar a bandeja",
                f"Não foi possível confirmar as coordenadas em:\n{CONFIG_PATH}\n\n{exc}",
            )
            self._refresh_capture_status()
            return

        self.config = saved_config
        self._refresh_capture_status()
        messagebox.showinfo(
            "Bandeja salva definitivamente",
            f"Coordenadas confirmadas em:\n{CONFIG_PATH}\n\n"
            f"Braço: {color}\nX={x:.2f}  Y={y:.2f}  Z={z:.2f}  R={r:.2f}°",
        )

    def _refresh_capture_status(self):
        if not hasattr(self, "capture_coord_var"):
            return
        arm_cfg = self.config.get("arms", {}).get(self.arm_color.get(), {})
        coords = [arm_cfg.get(f"capture_{axis}") for axis in ("x", "y", "z")]
        rotation = float(arm_cfg.get("capture_r", 0.0))
        if hasattr(self, "capture_stack_count_var"):
            self.capture_stack_count_var.set(
                f"Peças empilhadas: {int(arm_cfg.get('capture_stack_count', 0))}"
            )
        if hasattr(self, "capture_stack_step_var"):
            self.capture_stack_step_var.set(str(arm_cfg.get("capture_stack_step_mm", 5.0)))
        if all(value is not None for value in coords):
            self.capture_coord_var.set(
                "X={:.2f} mm   Y={:.2f} mm   Z={:.2f} mm   R={:.2f}°".format(
                    *(float(value) for value in coords), rotation
                )
            )
        else:
            self.capture_coord_var.set("Bandeja não calibrada — grave a posição atual")

    def reset_capture_stack_count(self):
        color = self.arm_color.get()
        arm_cfg = self.config.setdefault("arms", {}).setdefault(color, {})
        arm_cfg["capture_stack_count"] = 0
        try:
            self.save_config()
        except Exception as exc:
            messagebox.showerror(
                "Erro ao salvar",
                f"Não foi possível zerar a contagem em {CONFIG_PATH}:\n{exc}",
            )
            return
        self.capture_stack_count_var.set("Peças empilhadas: 0")
        messagebox.showinfo(
            "Contagem zerada", "A contagem foi zerada. Use isso somente depois de esvaziar a bandeja."
        )

    def auto_interpolate_all(self):
        """Interpola as 32 casas se ao menos A1 e H8 estiverem calibradas."""
        needed = ["a1", "h8"]
        if not all(k in self.squares_coords for k in needed):
            messagebox.showinfo(
                "Aviso",
                "Para interpolar todas as casas automaticamente, calibre primeiro:\n"
                "- A1 (PDN 1)\n"
                "- H8 (PDN 32)\n\n"
                "E de preferência G1 (PDN 4) e B8 (PDN 29) para máxima precisão!"
            )
            return

        a1 = self.squares_coords["a1"]
        h8 = self.squares_coords["h8"]

        if "g1" in self.squares_coords and "b8" in self.squares_coords:
            g1 = self.squares_coords["g1"]
            b8 = self.squares_coords["b8"]
            h1 = {
                "x": a1["x"] + (7.0/6.0)*(g1["x"] - a1["x"]),
                "y": a1["y"] + (7.0/6.0)*(g1["y"] - a1["y"]),
                "z": a1["z"] + (7.0/6.0)*(g1["z"] - a1["z"]),
                "r": a1.get("r", 0.0) + (7.0/6.0)*(g1.get("r", 0.0) - a1.get("r", 0.0)),
            }
            a8 = {
                "x": h8["x"] + (7.0/6.0)*(b8["x"] - h8["x"]),
                "y": h8["y"] + (7.0/6.0)*(b8["y"] - h8["y"]),
                "z": h8["z"] + (7.0/6.0)*(b8["z"] - h8["z"]),
                "r": h8.get("r", 0.0) + (7.0/6.0)*(b8.get("r", 0.0) - h8.get("r", 0.0)),
            }
        else:
            h1 = {"x": h8["x"], "y": a1["y"], "z": a1["z"], "r": a1.get("r", 0.0)}
            a8 = {"x": a1["x"], "y": h8["y"], "z": h8["z"], "r": h8.get("r", 0.0)}

        for sq in DRAUGHTS_SQUARES:
            file_idx = ord(sq[0].lower()) - ord("a")
            rank_idx = int(sq[1]) - 1
            u = file_idx / 7.0
            v = rank_idx / 7.0
            x = (1-u)*(1-v)*a1["x"] + u*(1-v)*h1["x"] + (1-u)*v*a8["x"] + u*v*h8["x"]
            y = (1-u)*(1-v)*a1["y"] + u*(1-v)*h1["y"] + (1-u)*v*a8["y"] + u*v*h8["y"]
            z = (1-u)*(1-v)*a1["z"] + u*(1-v)*h1["z"] + (1-u)*v*a8["z"] + u*v*h8["z"]
            r = (1-u)*(1-v)*a1.get("r", 0.0) + u*(1-v)*h1.get("r", 0.0) + (1-u)*v*a8.get("r", 0.0) + u*v*h8.get("r", 0.0)
            self.squares_coords[sq] = {"x": round(x, 2), "y": round(y, 2), "z": round(z, 2), "r": round(r, 2)}
            if sq in self.sq_buttons:
                self.sq_buttons[sq].config(bg="#2e7d32")

        self.lbl_calib_count.config(text=f"Casas gravadas: {len(self.squares_coords)} / 32")
        self.on_select_square(self.selected_sq.get())
        messagebox.showinfo("Sucesso", "Todas as 32 casas foram interpoladas!\nVocê pode clicar em qualquer uma para fazer ajustes finos.")

    def save_all_to_config(self):
        try:
            color = self.arm_color.get()
            arm_cfg = self.config.setdefault("arms", {}).setdefault(color, {})
            has_capture = all(arm_cfg.get(f"capture_{axis}") is not None for axis in "xyz")
            stack_step = float(self.capture_stack_step_var.get())
            if not 0.0 <= stack_step <= 20.0:
                raise ValueError("A subida Z deve ficar entre 0 e 20 mm.")
            arm_cfg["capture_stack_step_mm"] = stack_step
            if not self.squares_coords and not has_capture:
                messagebox.showwarning(
                    "Aviso", "Não há coordenadas de casas nem da bandeja para salvar."
                )
                return

            # Salvar square_overrides com cada uma das casas calibradas
            if self.squares_coords:
                arm_cfg["square_overrides"] = {}
                for sq, pt in self.squares_coords.items():
                    arm_cfg["square_overrides"][sq.upper()] = {
                        "x": float(round(pt["x"], 2)),
                        "y": float(round(pt["y"], 2)),
                        "z": float(round(pt["z"], 2)),
                        "r": float(round(pt.get("r", 0.0), 2)),
                    }

            # Calcular corners (A1, H1, A8, H8) para compatibilidade
            if "a1" in self.squares_coords and "h8" in self.squares_coords:
                arm_cfg.setdefault("corners", {})
                a1 = self.squares_coords["a1"]
                h8 = self.squares_coords["h8"]
                arm_cfg["corners"]["A1"] = {"x": float(a1["x"]), "y": float(a1["y"]), "z": float(a1["z"]), "r": float(a1.get("r", 0.0))}
                arm_cfg["corners"]["H8"] = {"x": float(h8["x"]), "y": float(h8["y"]), "z": float(h8["z"]), "r": float(h8.get("r", 0.0))}

                if "g1" in self.squares_coords and "b8" in self.squares_coords:
                    g1 = self.squares_coords["g1"]
                    b8 = self.squares_coords["b8"]
                    h1_x = a1["x"] + (7.0/6.0)*(g1["x"] - a1["x"])
                    h1_y = a1["y"] + (7.0/6.0)*(g1["y"] - a1["y"])
                    h1_z = a1["z"] + (7.0/6.0)*(g1["z"] - a1["z"])
                    a8_x = h8["x"] + (7.0/6.0)*(b8["x"] - h8["x"])
                    a8_y = h8["y"] + (7.0/6.0)*(b8["y"] - h8["y"])
                    a8_z = h8["z"] + (7.0/6.0)*(b8["z"] - h8["z"])
                    arm_cfg["corners"]["H1"] = {"x": float(round(h1_x, 2)), "y": float(round(h1_y, 2)), "z": float(round(h1_z, 2)), "r": float(round(a1.get("r", 0.0) + (7.0/6.0)*(g1.get("r", 0.0)-a1.get("r", 0.0)), 2))}
                    arm_cfg["corners"]["A8"] = {"x": float(round(a8_x, 2)), "y": float(round(a8_y, 2)), "z": float(round(a8_z, 2)), "r": float(round(h8.get("r", 0.0) + (7.0/6.0)*(b8.get("r", 0.0)-h8.get("r", 0.0)), 2))}

            # Altura média de pega (grip_z)
            all_zs = [pt["z"] for pt in self.squares_coords.values()]
            if all_zs:
                arm_cfg["grip_z"] = float(round(sum(all_zs) / len(all_zs), 2))

            self.save_config()
            saved_file = CONFIG_PATH.open("r", encoding="utf-8")
            try:
                saved_config = yaml.safe_load(saved_file) or {}
            finally:
                saved_file.close()
            saved_arm = saved_config.get("arms", {}).get(color, {})
            if self.squares_coords and len(saved_arm.get("square_overrides", {})) != len(self.squares_coords):
                raise OSError("A verificação das casas gravadas no YAML falhou.")
            if has_capture and any(
                saved_arm.get(f"capture_{axis}") != arm_cfg.get(f"capture_{axis}")
                for axis in "xyz"
            ):
                raise OSError("A verificação da bandeja gravada no YAML falhou.")
            self.config = saved_config
            messagebox.showinfo(
                "Sucesso",
                f"Coordenadas confirmadas em:\n{CONFIG_PATH}\n\n"
                f"Casas gravadas: {len(self.squares_coords)}\n"
                f"Bandeja de captura: {'gravada' if has_capture else 'não configurada'}"
            )
        except Exception as exc:
            messagebox.showerror("Erro ao Salvar", f"Falha ao salvar no arquivo de configuração:\n{exc}")

    def destroy(self):
        self.running = False
        if self.worker:
            self.worker.close()
            self.worker = None
        self.is_connected = False
        try:
            super().destroy()
        except tk.TclError:
            pass


def main():
    app = DraughtsCalibrationGUI()
    try:
        app.mainloop()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        app.destroy()


if __name__ == "__main__":
    main()
