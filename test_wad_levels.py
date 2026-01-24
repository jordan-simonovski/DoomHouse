import struct
import re
import os

def list_wad_levels(wad_path):
    if not os.path.exists(wad_path):
        print(f"File not found: {wad_path}")
        return

    with open(wad_path, 'rb') as f:
        header = f.read(12)
        ident, num_lumps, dict_offset = struct.unpack('<4sII', header)
        
        f.seek(dict_offset)
        lump_list = []
        for i in range(num_lumps):
            entry = f.read(16)
            pos, size, name = struct.unpack('<II8s', entry)
            name = name.decode('ascii').strip('\0').upper()
            lump_list.append({'name': name})

        level_pattern = re.compile(r'^(E\dM\d|MAP\d\d)$')
        all_levels = [l['name'] for l in lump_list if level_pattern.match(l['name'])]
        print(f"🗺️ Found {len(all_levels)} levels in WAD: {', '.join(all_levels)}")

if __name__ == "__main__":
    list_wad_levels("maps/Doom1.WAD")
