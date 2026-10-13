import sys
import yaml
from damas.robot.kinematics import BoardToRobot, grid_squares

def main():
    if len(sys.argv) < 2:
        print("Usage: python print_coords.py <config.yaml>")
        return

    with open(sys.argv[1], "r") as f:
        config = yaml.safe_load(f)

    kinematics_cfg = config.get("kinematics", {})
    b2r = BoardToRobot.from_config(kinematics_cfg)

    # Assumindo 8x8
    squares = grid_squares(8, 8)
    print("Coordenadas de cada casa (X, Y):")
    for sq in squares:
        x, y = b2r.to_xy(sq)
        print(f"{sq}: ({x:.2f}, {y:.2f})")

if __name__ == "__main__":
    main()
