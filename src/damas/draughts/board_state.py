"""Estado do tabuleiro de damas baseado em pydraughts para Damas Brasileiras."""

from __future__ import annotations

import draughts
from draughts.core.variant import Move
import re


class BoardState:
    """Wrapper sobre ``draughts.Board`` com helpers para o orquestrador."""

    def __init__(self, fen: str | None = None) -> None:
        if fen is not None:
            try:
                self.board = draughts.Board(variant='brazilian', fen=fen)
            except Exception:
                self.board = draughts.Board(fen)
        else:
            self.board = draughts.Board(variant='brazilian')

    @property
    def turn(self) -> int:
        return self.board.turn

    @property
    def turn_name(self) -> str:
        return "white" if self.board.turn == draughts.WHITE else "black"

    def legal_moves(self) -> list[Move]:
        return list(self.board.legal_moves())

    def is_legal(self, move: Move) -> bool:
        if move is None:
            return False
        try:
            legal = self.board.legal_moves()
            for lm in legal:
                if getattr(lm, 'pdn_move', None) == getattr(move, 'pdn_move', None):
                    return True
            return False
        except Exception:
            return False

    def san(self, move: Move) -> str:
        return move.pdn_move

    def apply(self, move: Move) -> None:
        self.board.push(move)

    def fen(self) -> str:
        return self.board.fen

    def is_game_over(self) -> bool:
        return self.board.is_over()

    def outcome(self) -> str:
        if not self.board.is_over():
            return ""
        if self.board.winner == draughts.WHITE:
            return "white"
        elif self.board.winner == draughts.BLACK:
            return "black"
        # Em pydraughts, partidas terminadas sem vencedor são empates.
        return "draw"

    def piece_map(self) -> dict[str, str]:
        # O searcher interno do pydraughts usa índices próprios que não
        # correspondem aos números PDN após um lance. O FEN mantém as casas
        # algébricas corretas e também identifica as damas com o prefixo K.
        sections = self.board.fen.split(":")
        out: dict[str, str] = {}
        for section in sections[1:]:
            if not section or section[0] not in ("W", "B"):
                continue
            color = section[0].lower()
            for token in section[1:].split(","):
                token = token.strip()
                match = re.fullmatch(r"(K)?([a-h][1-8])", token, re.IGNORECASE)
                if match:
                    is_king, square = match.groups()
                    symbol = color.upper() if is_king else color
                    out[square.lower()] = symbol
        return out

    def copy(self) -> "BoardState":
        return BoardState(self.board.fen)
