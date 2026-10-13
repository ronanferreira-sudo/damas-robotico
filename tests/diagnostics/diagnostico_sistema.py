"""Bateria de testes e diagnóstico completo do sistema de Damas Robótico.

Executa testes automatizados cobrindo:
1. Carregamento e integridade das configurações (default.yaml)
2. Regras e estado do tabuleiro de Damas Brasileiras (BoardState)
3. Motor de Inteligência Artificial / Minimax (engine.py)
4. Planejador de movimentos e capturas físicas (plan_actions)
5. Simulação de partida completa (Match em modo simulation)
6. Cinemática e mapeamento das 32 casas (BoardToRobot)
7. Sistema de visão computacional (Calibration e VisionSystem)

Gera um relatório detalhado de erros, avisos e pontos de atenção.
"""

from __future__ import annotations

import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import yaml
import draughts

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

REPORT = []

def log_test(category: str, name: str, success: bool, details: str = ""):
    status = "PASSOU" if success else "FALHOU"
    REPORT.append({
        "category": category,
        "name": name,
        "status": status,
        "success": success,
        "details": details
    })
    symbol = "OK" if success else "X"
    print(f"[{symbol:4s}] [{category}] {name}: {status}")
    if details and not success:
        print(f"       Detalhe: {details}")


# ─── 1. Testes de Configuração ────────────────────────────────────────────────

def test_config():
    cat = "Configuração"
    cfg_path = ROOT / "config" / "default.yaml"
    if not cfg_path.exists():
        log_test(cat, "Arquivo default.yaml existe", False, f"Arquivo não encontrado em {cfg_path}")
        return {}

    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        log_test(cat, "Leitura do default.yaml", True, "YAML válido")
    except Exception as e:
        log_test(cat, "Leitura do default.yaml", False, str(e))
        return {}

    # Checar seções
    arms = cfg.get("arms", {})
    if "white" in arms:
        w = arms["white"]
        corners = w.get("corners", {})
        overrides = w.get("square_overrides", {})
        log_test(cat, "Estrutura do braço white", True, f"Porta: {w.get('serial_port')}, {len(corners)} cantos, {len(overrides)} overrides")
    else:
        log_test(cat, "Estrutura do braço white", False, "Braço 'white' não definido")

    return cfg


# ─── 2. Testes de Estado do Tabuleiro (BoardState) ───────────────────────────

def test_board_state():
    cat = "BoardState (Damas)"
    try:
        from damas.draughts.board_state import BoardState

        bs = BoardState()
        log_test(cat, "Inicialização do BoardState", True, f"Variante: {bs.board.variant}")

        # Testar turno inicial
        if bs.turn_name == "white":
            log_test(cat, "Turno inicial é das brancas", True)
        else:
            log_test(cat, "Turno inicial é das brancas", False, f"Turno inicial retornado: {bs.turn_name}")

        # Testar lances legais iniciais
        moves = bs.legal_moves()
        if len(moves) > 0:
            log_test(cat, "Geração de lances legais iniciais", True, f"{len(moves)} lances possíveis gerados")
        else:
            log_test(cat, "Geração de lances legais iniciais", False, "Nenhum lance legal gerado na posição inicial!")

        # Testar piece_map
        pmap = bs.piece_map()
        white_count = sum(1 for p in pmap.values() if p.lower() == "w")
        black_count = sum(1 for p in pmap.values() if p.lower() == "b")
        if white_count == 12 and black_count == 12:
            log_test(cat, "Contagem de peças (12 Brancas x 12 Pretas)", True, f"Total de 24 peças mapeadas nas 32 casas")
        else:
            log_test(cat, "Contagem de peças (12 Brancas x 12 Pretas)", False, f"Encontradas {white_count} brancas e {black_count} pretas!")

        # Verificar se as casas das peças correspondem às casas jogáveis de damas
        invalid_squares = []
        for sq in pmap.keys():
            col_idx = ord(sq[0].lower()) - ord("a")
            rank = int(sq[1])
            if (col_idx + rank) % 2 != 1:
                invalid_squares.append(sq)
        if not invalid_squares:
            log_test(cat, "Pertinência das casas das peças (todas escuras)", True)
        else:
            log_test(cat, "Pertinência das casas das peças (todas escuras)", False, f"Peças em casas não jogáveis: {invalid_squares}")

        # Testar aplicação de lance
        first_move = moves[0]
        san = bs.san(first_move)
        bs.apply(first_move)
        log_test(cat, f"Aplicação de lance ({san})", True, f"Novo turno: {bs.turn_name}")

        # Testar FEN
        fen = bs.fen()
        if fen and ":" in fen:
            log_test(cat, "Geração de FEN", True, f"FEN: {fen[:35]}...")
        else:
            log_test(cat, "Geração de FEN", False, f"FEN inválido: {fen}")

    except Exception as e:
        log_test(cat, "Execução do BoardState", False, f"{traceback.format_exc()}")


# ─── 3. Testes do Motor de IA (engine.py) ─────────────────────────────────────

def test_engine():
    cat = "Motor de IA (Minimax)"
    try:
        from damas.draughts.board_state import BoardState
        from damas.draughts.engine import choose_move, _evaluate

        bs = BoardState()
        # Testar função de avaliação
        score_initial = _evaluate(bs.board)
        if score_initial == 0.0:
            log_test(cat, "Avaliação da posição inicial (equilibrada)", True, "Score = 0.0")
        else:
            log_test(cat, "Avaliação da posição inicial (equilibrada)", False, f"Score esperado 0.0, obtido {score_initial}")

        # Testar escolha de lance com depth 1
        t0 = time.time()
        m1 = choose_move(bs, minimax_depth=1)
        dt1 = (time.time() - t0) * 1000
        if m1 is not None and bs.is_legal(m1):
            log_test(cat, "Escolha de lance (Profundidade 1)", True, f"Lance: {m1.pdn_move} em {dt1:.1f}ms")
        else:
            log_test(cat, "Escolha de lance (Profundidade 1)", False, "Lance inválido ou nulo")

        # Testar escolha de lance com depth 2
        t0 = time.time()
        m2 = choose_move(bs, minimax_depth=2)
        dt2 = (time.time() - t0) * 1000
        if m2 is not None and bs.is_legal(m2):
            log_test(cat, "Escolha de lance (Profundidade 2)", True, f"Lance: {m2.pdn_move} em {dt2:.1f}ms")
        else:
            log_test(cat, "Escolha de lance (Profundidade 2)", False, "Lance inválido ou nulo")

    except Exception as e:
        log_test(cat, "Execução do Motor de IA", False, f"{traceback.format_exc()}")


# ─── 4. Testes de Planejamento de Movimento Físico (plan_actions) ─────────────

def test_plan_actions():
    cat = "Planejamento Físico (plan_actions)"
    try:
        from damas.game.match import plan_actions

        # Cenário 1: Movimento simples (sem captura)
        # Brancas movem c3 -> d4
        prev = {"c3": "w", "a1": "w"}
        new = {"d4": "w", "a1": "w"}
        actions = plan_actions(prev, new)
        expected = [("move", "white", "c3", "d4")]
        if actions == expected:
            log_test(cat, "Movimento simples de peça", True, str(actions))
        else:
            log_test(cat, "Movimento simples de peça", False, f"Esperado {expected}, obtido {actions}")

        # Cenário 2: Captura simples
        # Branca em c3 salta sobre preta em d4 e cai em e5
        prev = {"c3": "w", "d4": "b"}
        new = {"e5": "w"}
        actions = plan_actions(prev, new)
        moves = [a for a in actions if a[0] == "move"]
        captures = [a for a in actions if a[0] == "capture"]
        if ("move", "white", "c3", "e5") in moves and ("capture", "white", "d4", None) in captures:
            log_test(cat, "Movimento com captura simples", True, f"Captura d4 e move c3->e5")
        else:
            log_test(cat, "Movimento com captura simples", False, f"Ações geradas: {actions}")

        # Cenário 3: Captura múltipla (ex: come 2 peças)
        # Branca em c3 come d4 e f6, parando em g7
        prev = {"c3": "w", "d4": "b", "f6": "b"}
        new = {"g7": "w"}
        actions_multi = plan_actions(prev, new)
        caps = [a for a in actions_multi if a[0] == "capture"]
        mvs = [a for a in actions_multi if a[0] == "move"]
        cap_squares = {a[2] for a in caps}
        if cap_squares == {"d4", "f6"} and ("move", "white", "c3", "g7") in mvs:
            log_test(cat, "Captura múltipla (2 peças comidas no mesmo lance)", True, f"Detectou remoção de {cap_squares}")
        else:
            log_test(cat, "Captura múltipla (2 peças comidas no mesmo lance)", False, f"Ações: {actions_multi}")

    except Exception as e:
        log_test(cat, "Execução do plan_actions", False, f"{traceback.format_exc()}")


# ─── 5. Testes de Simulação de Partida (Match) ────────────────────────────────

def test_match_simulation(cfg):
    cat = "Simulação de Partida (Match)"
    try:
        import asyncio
        from damas.game import Match

        sim_cfg = dict(cfg)
        sim_cfg["mode"] = "simulation"
        sim_cfg["match"] = {
            "max_moves": 4,  # testar 4 lances simulados
            "move_delay": 0.0,
            "verify_with_vision": False
        }
        sim_cfg["engine"] = {
            "minimax_depth": 1,
            "players": {"white": "ai", "black": "ai"}
        }

        match = Match(sim_cfg, calibration=None)
        
        async def run_sim():
            await match.setup()
            try:
                res = await match.run()
                return res
            finally:
                await match.teardown()

        res = asyncio.run(run_sim())
        if match.move_count == 4:
            log_test(cat, "Execução de 4 lances simulados pela IA", True, f"Lances concluídos com sucesso (total: {match.move_count})")
        else:
            log_test(cat, "Execução de 4 lances simulados pela IA", False, f"Esperado 4 lances, executou {match.move_count}")

    except Exception as e:
        log_test(cat, "Execução da Simulação de Partida", False, f"{traceback.format_exc()}")


# ─── 6. Testes de Cinemática e Mapeamento das 32 Casas ────────────────────────

def test_kinematics(cfg):
    cat = "Cinemática (BoardToRobot)"
    try:
        from damas.robot.kinematics import BoardToRobot

        # Testar com square_overrides
        sample_overrides = {
            "A1": {"x": 180.0, "y": 80.0, "z": 15.0},
            "H8": {"x": 320.0, "y": -90.0, "z": 14.0}
        }
        kin = BoardToRobot(square_overrides=sample_overrides)
        x, y, z = kin.to_xyz_interpolated("a1", fallback_z=0.0)
        if (x, y, z) == (180.0, 80.0, 15.0):
            log_test(cat, "Prioridade de square_overrides", True, f"a1 retornou exatamente os valores gravados: ({x}, {y}, {z})")
        else:
            log_test(cat, "Prioridade de square_overrides", False, f"Obtido: ({x}, {y}, {z})")

        # Testar interpolação bilinear a partir dos 4 cantos
        corners = {
            "A1": {"x": 180.0, "y": 80.0, "z": 10.0},
            "H1": {"x": 180.0, "y": -80.0, "z": 10.0},
            "A8": {"x": 320.0, "y": 80.0, "z": 10.0},
            "H8": {"x": 320.0, "y": -80.0, "z": 10.0},
        }
        kin_corners = BoardToRobot(corners=corners)
        mid_x, mid_y, mid_z = kin_corners.to_xyz_interpolated("d4", fallback_z=10.0)
        # d4: file d=3 (3/7), rank 4=3 (3/7)
        expected_x = 180.0 + (3.0/7.0)*(320.0 - 180.0)
        if abs(mid_x - expected_x) < 1e-4:
            log_test(cat, "Interpolação bilinear das casas centrais", True, f"d4 interpolado corretamente em X={mid_x:.2f} Y={mid_y:.2f}")
        else:
            log_test(cat, "Interpolação bilinear das casas centrais", False, f"X esperado {expected_x:.2f}, obtido {mid_x:.2f}")

        # Testar as 32 casas jogáveis
        all_ok = True
        draughts_squares = [
            f"{chr(ord('a')+f)}{r}" for r in range(1, 9) for f in range(8) if (f + r) % 2 == 1
        ]
        for sq in draughts_squares:
            try:
                coords = kin_corners.to_xyz_interpolated(sq, 0.0)
                if len(coords) != 3:
                    all_ok = False
            except Exception:
                all_ok = False
        log_test(cat, "Validação de coordenadas para as 32 casas de damas", all_ok, f"Total de 32 casas verificadas")

    except Exception as e:
        log_test(cat, "Execução da Cinemática", False, f"{traceback.format_exc()}")


# ─── 7. Testes de Visão e Detector ────────────────────────────────────────────

def test_vision():
    cat = "Visão Computacional"
    try:
        from damas.vision.calibration import Calibration
        calib = Calibration.build_from_corners((50, 50), (50, 400), (400, 50), (400, 400), roi_size=32)
        if len(calib.square_centers) == 64:
            log_test(cat, "Geração de matriz de calibração", True, "64 centros de casas calculados")
        else:
            log_test(cat, "Geração de matriz de calibração", False, f"Centros: {len(calib.square_centers)}")

        from damas.vision.detector import BoardDetector
        detector = BoardDetector(calib, {"occupancy_threshold": 0.20, "method": "template"})
        log_test(cat, "Inicialização do BoardDetector", True)

    except Exception as e:
        log_test(cat, "Módulo de Visão", False, f"{traceback.format_exc()}")


# ─── Relatório Final ──────────────────────────────────────────────────────────

def main():
    print("=" * 65)
    print("   BATERIA DE TESTES E DIAGNÓSTICO DO SISTEMA DE DAMAS   ")
    print("=" * 65)

    cfg = test_config()
    test_board_state()
    test_engine()
    test_plan_actions()
    if cfg:
        test_kinematics(cfg)
        test_match_simulation(cfg)
    test_vision()

    print("\n" + "=" * 65)
    print("                    RESUMO DO DIAGNÓSTICO")
    print("=" * 65)
    total = len(REPORT)
    passed = sum(1 for r in REPORT if r["success"])
    failed = total - passed

    print(f"Total de testes executados: {total}")
    print(f"Testes Aprovados:          {passed}")
    print(f"Falhas Detectadas:         {failed}")

    if failed > 0:
        print("\nITENS QUE REQUEREM ATENÇÃO / CORREÇÃO:")
        for r in REPORT:
            if not r["success"]:
                print(f"  • [{r['category']}] {r['name']}: {r['details']}")
    else:
        print("\nTodos os módulos internos do sistema estão funcionando perfeitamente!")

    print("=" * 65)


if __name__ == "__main__":
    main()
