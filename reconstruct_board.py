content = '''"""Estado do tabuleiro de damas baseado em pydraughts para Damas Brasileiras."""

from __future__ import annotations

import draughts
from draughts.core.variant import Move


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
        if self.board.is_draw():
            return "draw"
        if self.board.winner == draughts.WHITE:
            return "white"
        elif self.board.winner == draughts.BLACK:
            return "black"
        return "draw"

    def piece_map(self) -> dict[str, str]:
        pdn_to_sq = {
            1: "a1", 2: "c1", 3: "e1", 4: "g1",
            5: "b2", 6: "d2", 7: "f2", 8: "h2",
            9: "a3", 10: "c3", 11: "e3", 12: "g3",
            13: "b4", 14: "d4", 15: "f4", 16: "h4",
            17: "a5", 18: "c5", 19: "e5", 20: "g5",
            21: "b6", 22: "d6", 23: "f6", 24: "h6",
            25: "a7", 26: "c7", 27: "e7", 28: "g7",
            29: "b8", 30: "d8", 31: "f8", 32: "h8",
        }
        out = {}
        for pos in self.board._game.board.searcher.filled_positions:
            piece = self.board._game.board.searcher.get_piece_by_position(pos)
            if piece:
                sym = "W" if piece.player == draughts.WHITE else "B"
                if not piece.king:
                    sym = sym.lower()
                sq = pdn_to_sq.get(pos, str(pos))
                out[sq] = sym
        return out

    def copy(self) -> "BoardState":
        return BoardState(self.board.fen)
'''
with open(r"C:\projetos\xadrez\src\damas\draughts\board_state.py", 'w', encoding='utf-8') as f:
    f.write(content)
print('ok')
