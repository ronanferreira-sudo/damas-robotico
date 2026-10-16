import re
with open('config/default.yaml', 'r') as f:
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

def fix_corners_block(section):
    # find corners line
    for i, line in enumerate(section):
        if re.match(r'^\s{4}corners:\s*$', line):
            key_idx = i
            break
    else:
        return section
    key_line = section[key_idx]
    m = re.match(r'^( *)', key_line)
    key_indent = len(m.group(1))
    # find end of block
    j = key_idx + 1
    while j < len(section) and re.match(r'^( {' + str(key_indent+2) + r',})', section[j]):
        j += 1
    # lines[key_idx+1:j] are the value lines
    val_lines = section[key_idx+1:j]
    # parse groups of 4 lines (x,y,z,r)
    groups = []
    p = 0
    while p + 3 < len(val_lines):
        groups.append([val_lines[p+k].rstrip('\\n') for k in range(4)])
        p += 4
    # Determine explicit keys from lines that look like \"H8:\" at indent key_indent
    explicit_keys = []
    for line in val_lines:
        if re.match(r'^( {' + str(key_indent) + r'})\\S+:', line):
            m = re.match(r'^( {' + str(key_indent) + r'})(\\S+):', line)
            explicit_keys.append(m.group(2))
    # explicit_keys should be ['H8','H1','A8']
    # Build keys list: first missing => A1, then explicit_keys
    keys = ['A1'] + explicit_keys
    # Build new block
    new_section = section[:key_idx+1]
    for gi, g in enumerate(groups):
        if gi < len(keys):
            key = keys[gi]
        else:
            key = f'UNKNOWN{gi}'
        new_section.append(' ' * key_indent + f'{key}:\\n')
        for gl in g:
            new_section.append(' ' * (key_indent+2) + gl + '\\n')
    # append remainder
    new_section.extend(section[j:])
    return new_section

def fix_square_overrides_block(section):
    for i, line in enumerate(section):
        if re.match(r'^\s{4}square_overrides:\\s*$', line):
            key_idx = i
            break
    else:
        return section
    key_line = section[key_idx]
    m = re.match(r'^( *)', key_line)
    key_indent = len(m.group(1))
    # find end of block
    j = key_idx + 1
    while j < len(section) and re.match(r'^( {' + str(key_indent+2) + r',})', section[j]):
        j += 1
    # Now we have lines[key_idx+1:j] which contain entries.
    # Each entry is either:
    #   - a key line (e.g., 'C1:') at indent key_indent
    #   - followed by 4 lines x,y,z,r at indent key_indent+2
    #   - OR for the first entries, missing key line, just 4 lines x,y,z,r
    # We need to remove the first four entries (whether they have key or not).
    # We'll parse sequentially.
    entries = []  # each entry is (key_or_none, [x,y,z,r lines])
    p = key_idx + 1
    while p < j:
        line = section[p]
        # Check if this line is a key line at exact key_indent
        if re.match(r'^( {' + str(key_indent) + r'})\\S+:', line):
            # key line
            m = re.match(r'^( {' + str(key_indent) + r'})(\\S+):', line)
            key = m.group(2)
            p += 1
            # next 4 lines should be x,y,z,r
            vals = []
            for _ in range(4):
                if p >= j: break
                vals.append(section[p].rstrip('\\n'))
                p += 1
            entries.append((key, vals))
        else:
            # no key line, treat as 4 lines vals
            vals = []
            for _ in range(4):
                if p >= j: break
                vals.append(section[p].rstrip('\\n'))
                p += 1
            entries.append((None, vals))
    # Remove first four entries
    entries = entries[4:]
    # Rebuild block
    new_section = section[:key_idx+1]
    for key, vals in entries:
        if key is None:
            # Should not happen after removal, but just in case
            # We'll need to assign a placeholder? We'll skip.
            continue
        new_section.append(' ' * key_indent + f'{key}:\\n')
        for v in vals:
            new_section.append(' ' * (key_indent+2) + v + '\\n')
    new_section.extend(section[j:])
    return new_section

# Apply fixes
fixed = fix_corners_block(white_lines)
fixed = fix_square_overrides_block(fixed)
# Replace white section
new_lines = lines[:white_start] + fixed + lines[black_start:]
with open('config/default.yaml', 'w') as f:
    f.writelines(new_lines)
print('Fixed corners and square_overrides (removed first four entries)')