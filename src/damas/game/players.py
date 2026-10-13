"""Jogadores da partida (I.A. ou humano)."""

from __future__ import annotations

import logging
from typing import Mapping, Any

from ..draughts.board_state import BoardState
from ..draughts.engine import choose_move

logger = logging.getLogger(__name__)


class Player:
    def __init__(self, color: str) -> None:
        self.color = color  # "white" | "black"

    def choose(self, state: BoardState) -> Any | None:  # pragma: no cover
        raise NotImplementedError


class AIPlayer(Player):
    def __init__(self, color: str, engine_cfg: Mapping) -> None:
        super().__init__(color)
        self.engine_cfg = engine_cfg

    def choose(self, state: BoardState) -> Any | None:
        return choose_move(
            state,
            backend=self.engine_cfg.get("backend", "auto"),
            stockfish_path=self.engine_cfg.get("stockfish_path"),
            think_time=float(self.engine_cfg.get("think_time", 1.0)),
            minimax_depth=int(self.engine_cfg.get("minimax_depth", 3)),
        )


class HumanPlayer(Player):
    def choose(self, state: BoardState) -> Any | None:
        print(f"\nVez das {'brancas' if self.color == 'white' else 'pretas'}.")
        print("Lances legais (PDN):", " ".join(m.pdn_move for m in state.legal_moves()))
        while True:
            raw = input("Seu lance (ex.: 11-15 ou 11x18): ").strip()
            if not raw:
                return None
            
            for move in state.legal_moves():
                if move.pdn_move == raw:
                    return move
            
            print("Lance ilegal ou formato invalido. Tente novamente.")
