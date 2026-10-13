import argparse
import asyncio
import logging

from dobot import Robot


def setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


async def cmd_home(args: argparse.Namespace) -> None:
    async with Robot(args.host, args.port) as robot:
        await robot.motion.home()


async def cmd_square(args: argparse.Namespace) -> None:
    async with Robot(args.host, args.port) as robot:
        await robot.canvas.start()
        await robot.drawer.draw_square(100, 100, args.size, z=0)
        await robot.canvas.stop()


async def cmd_circle(args: argparse.Namespace) -> None:
    async with Robot(args.host, args.port) as robot:
        await robot.canvas.start()
        await robot.drawer.draw_circle(200, 200, args.radius, z=0)
        await robot.canvas.stop()


async def cmd_status(args: argparse.Namespace) -> None:
    async with Robot(args.host, args.port) as robot:
        pose = await robot.dashboard.get_pose()
        print("Pose:", pose)
        alarm = await robot.dashboard.get_alarm()
        print("Alarm:", alarm)
        version = await robot.dashboard.get_version()
        print("Version:", version)


def main() -> None:
    parser = argparse.ArgumentParser(description="DobotDraw CLI")
    parser.add_argument("--host", default="127.0.0.1", help="Host do servidor RPC")
    parser.add_argument("--port", type=int, default=9090, help="Porta do servidor RPC")
    parser.add_argument("-v", "--verbose", action="store_true", help="Habilita logs detalhados")

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("home", help="Vai para posição de home")

    p_square = sub.add_parser("square", help="Desenha um quadrado")
    p_square.add_argument("--size", type=float, default=50, help="Tamanho do lado em mm")

    p_circle = sub.add_parser("circle", help="Desenha um círculo")
    p_circle.add_argument("--radius", type=float, default=30, help="Raio em mm")

    sub.add_parser("status", help="Mostra status do robô")

    args = parser.parse_args()
    setup_logging(args.verbose)

    if args.command == "home":
        asyncio.run(cmd_home(args))
    elif args.command == "square":
        asyncio.run(cmd_square(args))
    elif args.command == "circle":
        asyncio.run(cmd_circle(args))
    elif args.command == "status":
        asyncio.run(cmd_status(args))


if __name__ == "__main__":
    main()
