# Damas com braço robótico

Projeto para jogar Damas Brasileiras contra a IA e executar movimentos com braços Dobot Magician Lite. Inclui interface gráfica, calibração de coordenadas, visão computacional e modo de simulação.

## Instalação

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
```

## Uso

```powershell
damas play_gui                 # Jogo gráfico contra a IA
damas setup_arms               # Conectar e calibrar o braço
damas play --mode simulation   # Partida pela linha de comando
```

O jogo usa o único braço branco conectado à COM3. Os parâmetros locais do robô ficam em `config/default.yaml`.

## Estrutura

- `src/damas/draughts/`: estado do tabuleiro e motor de Damas.
- `src/damas/game/`: regras da partida e planejamento dos movimentos e capturas.
- `src/damas/robot/` e `src/damas/dobot/`: controle dos braços Dobot.
- `src/damas/vision/`: câmera, detecção e calibração.
- `tools/`: interfaces gráficas e ferramentas de configuração.
