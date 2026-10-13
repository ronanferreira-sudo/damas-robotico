"""Motor de Damas / I.A. para escolha de lances."""

from __future__ import annotations

import logging
import random
from typing import Callable

import draughts
from draughts.core.variant import Move

from .board_state import BoardState

logger = logging.getLogger(__name__)

def _evaluate(board: draughts.Board) -> float:
    if board.is_over():
        if board.winner is None:
            return 0.0
        if board.winner == draughts.WHITE:
            return 10000.0
        return -10000.0

    score = 0.0
    for pos in board._game.board.searcher.filled_positions:
        piece = board._game.board.searcher.get_piece_by_position(pos)
        if piece:
            val = 10 if not piece.king else 30
            if piece.player == draughts.WHITE:
                score += val
            else:
                score -= val
    return score

def _negamax(board: draughts.Board, depth: int, alpha: float, beta: float, color: int) -> float:
    if board.is_over() or depth == 0:
        return _evaluate(board) * color

    best = -float("inf")
    for move in board.legal_moves():
        board.push(move)
        val = -_negamax(board, depth - 1, -beta, -alpha, -color)
        board.pop()
        if val > best:
            best = val
        if best > alpha:
            alpha = best
        if alpha >= beta:
            break
    return best

def _choose_minimax(board: draughts.Board, depth: int) -> Move | None:
    best_move: Move | None = None
    best_val = -float("inf")
    alpha = -float("inf")
    beta = float("inf")
    color = 1 if board.turn == draughts.WHITE else -1
    moves = list(board.legal_moves())
    if not moves:
        return None
    
    # Shuffle to add some variety
    random.shuffle(moves)

    for move in moves:
        board.push(move)
        val = -_negamax(board, depth - 1, -beta, -alpha, -color)
        board.pop()
        if val > best_val:
            best_val = val
            best_move = move
        if val > alpha:
            alpha = val
    return best_move

def choose_move(
    state: BoardState,
    *,
    backend: str = "auto",
    stockfish_path: str | None = None,
    think_time: float = 1.0,
    minimax_depth: int = 3,
    rng: Callable[[], float] | None = None,
) -> Move | None:
    board = state.board
    if board.is_over():
        return None

    # Fallback always to minimax for now
    return _choose_minimax(board, max(1, minimax_depth))
