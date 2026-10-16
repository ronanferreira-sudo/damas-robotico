import re

def fix_corners_block(lines, start_idx):
    # Find corners line within lines[start_idx:]
    # We'll search from start_idx forward
    for i in range(start_idx, len(lines)):
        if re.match(r'^\s{4}corners:\s*$', lines[i]):
            key_idx = i
            break
    else:
        return start_idx  # not found, return unchanged start
    key_line = lines[key_idx]
    key_match = re.match(r'^( *)', key_line)
    key_indent = len(key_match.group(1)) if key_match else 0
    # Find end of block: first line after key_idx that has indent <= key_indent and starts with non-space
    j = key_idx + 1
    while j < len(lines) and re.match(r'^( {' + str(key_indent+2) + r',})', lines[j]):
        j += 1
    # Now lines[key_idx+1:j] are the value lines
    val_lines = lines[key_idx+1:j]
    # Parse groups of 4 lines (x,y,z,r)
    groups = []
    p = 0
    while p + 3 < len(val_lines):
        groups.append([val_lines[p+k].rstrip('\n') for k in range(4)])
        p += 4
    # Determine explicit keys from lines that look like "H8:" at indent key_indent
    explicit_keys = []
    for line in val_lines:
        if re.match(r'^( {' + str(key_indent) + r'})\\S+:', line):
            m = re.match(r'^( {' + str(key_indent) + r'})(\\S+):', line)
            explicit_keys.append(m.group(2))
    # explicit_keys should be ['H8','H1','A8']
    keys = ['A1'] + explicit_keys  # first missing key is A1
    # Build new block
    new_lines = lines[:key_idx+1]
    for gi, g in enumerate(groups):
        if gi < len(keys):
            key = keys[gi]
        else:
            key = f'UNKNOWN{gi}'
        new_lines.append(' ' * key_indent + f'{key}:\\n')
        for gl in g:
            new_lines.append(' ' * (key_indent+2) + gl + '\\n')
    new_lines.extend(lines[j:])
    return new_lines

def fix_square_overrides_block(lines, start_idx):
    for i in range(start_idx, len(lines)):
        if re.match(r'^\s{4}square_overrides:\s*$', lines[i]):
            key_idx = i
            break
    else:
        return start_idx
    key_line = lines[key_idx]
    key_match = re.match(r'^( *)', key_line)
    key_indent = len(key_match.group(1)) if key_match else 0
    # Find end of block
    j = key_idx + 1
    while j < len(lines) and re.match(r'^( {' + str(key_indent+2) + r',})', lines[j]):
        j += 1
    # Now we have lines[key_idx+1:j] which contain entries.
    entries = []  # each entry is (key_or_none, [x,y,z,r lines])
    p = key_idx + 1
    while p < j:
        line = lines[p]
        # Check if this line is a key line at exact key_indent
        if re.match(r'^( {' + str(key_indent) + r'})\\S+:', line):
            m = re.match(r'^( {' + str(key_indent) + r'})(\\S+):', line)
            key = m.group(2)
            p += 1
            vals = []
            for _ in range(4):
                if p >= j: break
                vals.append(lines[p].rstrip('\n'))
                p += 1
            entries.append((key, vals))
        else:
            # no key line, treat as 4 lines vals
            vals = []
            for _ in range(4):
                if p >= j: break
                vals.append(lines[p].rstrip('\n'))
                p += 1
            entries.append((None, vals))
    # Remove first four entries
    entries = entries[4:]
    # Rebuild block
    new_lines = lines[:key_idx+1]
    for key, vals in entries:
        if key is None:
            # Should not happen after removal, but just in case
            # We'll skip.
            continue
        new_lines.append(' ' * key_indent + f'{key}:\\n')
        for v in vals:
            new_lines.append(' ' * (key_indent+2) + v + '\\n')
    new_lines.extend(lines[j:])
    return new_lines

with open('config/default.yaml.bak', 'r') as f:
    lines = f.readlines()

# Find white section
white_start = None
for i, line in enumerate(lines):
    if re.match(r'^\s{2}white:\s*$', line):
        white_start = i
        break
if white_start is None:
    raise ValueError('white not found')
black_start = None
for i in range(white_start+1, len(lines)):
    if re.match(r'^\s{2}black:\s*$', lines[i]):
        black_start = i
        break
if black_start is None:
    raise ValueError('black not found after white')
white_lines = lines[white_start:black_start]

# Fix corners
fixed = fix_corners_block(white_lines, white_start)
# Fix square_overrides
fixed = fix_square_overrides_block(fixed, white_start)
# Replace white section
new_lines = lines[:white_start] + fixed + lines[black_start:]
with open('config/default_fixed.yaml', 'w') as f:
    f.writelines(new_lines)
print('Fixed corners and square_overrides')
