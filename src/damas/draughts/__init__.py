"""Pacote de damas: estado do tabuleiro e motor de I.A."""

from .board_state import BoardState
from .engine import choose_move

__all__ = ["BoardState", "choose_move"]
