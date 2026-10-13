import asyncio
import logging
from pathlib import Path
import yaml
import sys

# Garante que o pacote damas seja encontrado
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from damas.robot.arm import Arm

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

def load_config() -> dict:
    cfg_path = Path(__file__).resolve().parents[1] / "config" / "default.yaml"
    with open(cfg_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

async def main():
    config = load_config()
    
    white_cfg = config.get("arms", {}).get("white", {})
    black_cfg = config.get("arms", {}).get("black", {})
    
    arm_white = Arm("white", white_cfg)
    arm_black = Arm("black", black_cfg)
    
    print("Conectando braços...")
    await arm_white.connect()
    await arm_black.connect()
    
    try:
        print("1. Levando os dois braços para Home...")
        await arm_white.home()
        await arm_black.home()
        
        # Pausa para estabilizar
        await asyncio.sleep(2)
        
        print("2. Braço Branco move peça de A1 para A5...")
        await arm_white.move_piece("a1", "a5")
        
        print("3. Braço Branco volta para Home...")
        await arm_white.home()
        
        await asyncio.sleep(2)
        
        print("4. Braço Preto move peça de H1 para H6...")
        await arm_black.move_piece("h1", "h6")
        
        print("5. Braço Preto volta para Home...")
        await arm_black.home()
        
        print("Sequência concluída com sucesso!")
        
    finally:
        print("Desconectando...")
        await arm_white.disconnect()
        await arm_black.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
