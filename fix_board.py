import sys
with open(r"C:\projetos\xadrez\src\damas\draughts\board_state.py", 'r', encoding='utf-8') as f:
    data = f.read()
idx = data.find('    def turn')
if idx >= 0:
    rest = data[idx:]
else:
    rest = data
clean_head = '''"""Estado do tabuleiro de damas baseado em pydraughts para Damas Brasileiras."""

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
'''
with open(r"C:\projetos\xadrez\src\damas\draughts\board_state.py", 'w', encoding='utf-8') as f:
    f.write(clean_head + rest)
print('ok')
