"""Orquestrador da partida de damas com bracos roboticos.

Em modo "simulation" roda sem hardware (visao = verdade do tabuleiro).
Em modo "hardware" conecta os bracos Dobot e as cameras, executa os lances
fisicamente e reconfere o tabuleiro com a visao apos cada jogada.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any

from ..draughts.board_state import BoardState
from ..vision.calibration import Calibration
from .players import AIPlayer, HumanPlayer, Player

logger = logging.getLogger(__name__)


def plan_actions(prev: dict[str, str], new: dict[str, str]) -> list[tuple[str, str, str | None]]:
    """Calcula as acoes fisicas (mover/remover) a partir do delta do tabuleiro.

    Retorna lista de tuplas:
      ("move",   cor,   de,   para)   -> braco da `cor` move peca de->para
      ("capture", cor,  sq,   None)   -> braco da `cor` remove peca capturada em sq
    Ordem da lista: capturas primeiro, depois movimentos.
    """
    removed = {sq: sym for sq, sym in prev.items() if new.get(sq) != sym}
    added = {sq: sym for sq, sym in new.items() if prev.get(sq) != sym}

    actions: list[tuple[str, str, str | None]] = []
    used_from: set[str] = set()

    for color in ("white", "black"):
        rem = {sq: sym for sq, sym in removed.items() if (sym.lower() == "w" if color == "white" else sym.lower() == "b")}
        add = {sq: sym for sq, sym in added.items() if (sym.lower() == "w" if color == "white" else sym.lower() == "b")}

        rem_by_sym: dict[str, list[str]] = defaultdict(list)
        for sq, sym in rem.items():
            rem_by_sym[sym].append(sq)

        for to_sq, sym in add.items():
            from_sq = None
            if rem_by_sym.get(sym):
                from_sq = rem_by_sym[sym].pop(0)
            else:
                pawn = "w" if color == "white" else "b"
                if rem_by_sys := rem_by_sym.get(pawn):
                    from_sq = rem_by_sys.pop(0)  # promocao
            if from_sq is None:
                any_sym = next(iter(rem_by_sym), None)
                if any_sym is not None and rem_by_sym[any_sym]:
                    from_sq = rem_by_sym[any_sym].pop(0)
            if from_sq is not None:
                used_from.add(from_sq)
                actions.append(("move", color, from_sq, to_sq))


    captured_squares = set(removed) - used_from
    for sq in captured_squares:
        sym = removed[sq]
        opp = "black" if sym.lower() == "w" else "white"
        actions.append(("capture", opp, sq, None))


    # Capturas primeiro para liberar o quadrado de destino.
    captures = [a for a in actions if a[0] == "capture"]
    moves = [a for a in actions if a[0] == "move"]
    return captures + moves


class Match:
    def __init__(self, config: dict[str, Any], calibration: Calibration | None = None) -> None:
        self.config = config
        self.calib = calibration
        self.mode = str(config.get("mode", "simulation"))
        self.state = BoardState()
        self.players: dict[str, Player] = {}
        self.arms: dict[str, Any] = {}
        self.vision = None
        self.move_count = 0
        self.max_moves = int(config.get("match", {}).get("max_moves", 0))
        self.move_delay = float(config.get("match", {}).get("move_delay", 0.0))
        self.verify = bool(config.get("match", {}).get("verify_with_vision", True))

    # -- setup -------------------------------------------------------------

    def _build_players(self) -> None:
        engine_cfg = self.config.get("engine", {})
        players_cfg = engine_cfg.get("players", {"white": "ai", "black": "ai"})
        for color in ("white", "black"):
            kind = str(players_cfg.get(color, "ai")).lower()
            if kind == "human":
                self.players[color] = HumanPlayer(color)
            else:
                self.players[color] = AIPlayer(color, engine_cfg)

    async def setup(self) -> None:
        self._build_players()
        if self.mode == "hardware":
            await self._setup_hardware()
        else:
            await self._setup_simulation()

    async def _setup_hardware(self) -> None:
        from ..robot.arm import Arm, find_all_dobot_ports

        arms_cfg = self.config.get("arms", {})
        auto_ports = find_all_dobot_ports()
        logger.info("Portas Dobot encontradas: %s", auto_ports)

        # Distribui as portas detectadas apenas entre os braços que pedem "auto".
        auto_needed = [
            color for color in ("white", "black")
            if str(arms_cfg.get(color, {}).get("serial_port", "auto")).lower() == "auto"
        ]
        assignments = {}
        for i, color in enumerate(auto_needed):
            assignments[color] = auto_ports[i % len(auto_ports)] if auto_ports else None

        for color in ("white", "black"):
            cfg = arms_cfg.get(color, {})
            if not cfg.get("enabled", False):
                continue
            serial_port = assignments.get(color)
            arm = Arm(color, cfg, serial_port=serial_port)
            logger.info("[%s] porta=%s", color, arm.serial_port)
            try:
                await arm.connect()
                await arm.home()
                self.arms[color] = arm
            except Exception as exc:  # noqa: BLE001
                logger.warning("[%s] falha ao conectar/deslocar: %s", color, exc)

    async def _setup_simulation(self) -> None:
        pass

    # -- execucao ----------------------------------------------------------

    async def _execute(self, actions: list[tuple[str, str, str | None]]) -> None:
        hardware = self.mode == "hardware" and self.arms
        available_arms = list(self.arms.values())
        single_arm = available_arms[0] if hardware and available_arms else None

        for action in actions:
            kind, color, a, b = action
            arm = single_arm
            if kind == "capture":
                sq = a
                logger.info("ACAO: (Braco unico) captura em %s (peca %s)", sq, color)
                if arm is not None:
                    await arm.remove_captured(sq)
                elif hardware:
                    logger.warning("ACAO: Captura em %s ignorada fisicamente", sq)
            else:  # move
                frm, to = a, b
                logger.info("ACAO: (Braco unico) move %s -> %s (peca %s)", frm, to, color)
                if arm is not None:
                    await arm.move_piece(frm, to)
                elif hardware:
                    logger.warning("ACAO: Movimento %s -> %s ignorado fisicamente", frm, to)
        if hardware and self.move_delay:
            await asyncio.sleep(self.move_delay)

    async def _verify(self) -> bool:
        return True

    # -- loop principal ----------------------------------------------------

    async def run(self) -> str:
        print(f"=== Iniciando partida (modo: {self.mode}) ===")
        print(self.state.board)
        while not self.state.is_game_over():
            if self.max_moves and self.move_count >= self.max_moves:
                print("Limite de lances atingido.")
                break
            color = self.state.turn_name
            player = self.players[color]
            move = player.choose(self.state)
            if move is None:
                print("Jogador desistiu.")
                break

            prev_map = self.state.piece_map()
            san = self.state.san(move)
            self.state.apply(move)
            new_map = self.state.piece_map()
            self.move_count += 1

            print(f"Lance {self.move_count}: {color} joga {san}")
            actions = plan_actions(prev_map, new_map)
            await self._execute(actions)
            # Sem verificação de visão

        winner = self.state.outcome()
        if winner == "white":
            print("\n>>> AS BRANCAS VENCERAM! <<<")
        elif winner == "black":
            print("\n>>> AS PRETAS VENCERAM! <<<")
        else:
            print("\n>>> EMPATE / FIM DE JOGO <<<")
        print(self.state.board)
        return winner

    async def teardown(self) -> None:
        for arm in self.arms.values():
            try:
                await arm.disconnect()
            except Exception:  # noqa: BLE001
                pass



def _color_short(symbol: str | None) -> str | None:
    if not symbol:
        return None
    return "white" if symbol.lower() == "w" else "black"
