lines = open("config/default_fixed2.yaml", "r").readlines()
for i, line in enumerate(lines):
    if i >= 50 and i <= 90:
        visible = line.rstrip("\n").replace(" ", ".")
        print("{}: {}".format(i+1, visible))
