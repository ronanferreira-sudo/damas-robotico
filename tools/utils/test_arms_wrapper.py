import asyncio
import logging
from damas.dobot.usb_client import USBClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_wrapper")

async def test_wrapper():
    ports = ["COM5", "COM4"]
    for p in ports:
        logger.info(f"=== Testando via USBClient: {p} ===")
        client = USBClient(port=p)
        try:
            await client.connect()
            logger.info("Enviando comando HOME via wrapper...")
            await client.send_command("set_homecmd", {})
            await asyncio.sleep(4)
            pose = await client.send_command("get_pose", {})
            logger.info(f"Pose: {pose}")
            
            logger.info("Movendo para (200, 0, 50)...")
            await client.send_command("set_ptpcmd", {"ptp_mode": 1, "x": 200, "y": 0, "z": 50, "r": 0})
            await asyncio.sleep(3)
            pose = await client.send_command("get_pose", {})
            logger.info(f"Nova Pose: {pose}")
        except Exception as e:
            logger.error(f"Erro em {p}: {e}")
        finally:
            await client.disconnect()

if __name__ == "__main__":
    asyncio.run(test_wrapper())
