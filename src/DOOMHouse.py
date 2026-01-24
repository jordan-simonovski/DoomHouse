import chdb
import clickhouse_connect
import sys
import array
import math
import os
import time
import struct
import re
import tkinter as tk
from PIL import Image, ImageDraw, ImageFont, ImageTk
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# ---------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------
HOST = os.getenv('CLICKHOUSE_HOST', 'localhost')
PORT = int(os.getenv('CLICKHOUSE_PORT', '8123'))
USER = os.getenv('CLICKHOUSE_USER', 'default')
PASS = os.getenv('CLICKHOUSE_PASS', '')
USE_CHDB = os.getenv('USE_CHDB', 'true').lower() == 'true'

# Movement Constants
MOVE_SPEED = 0.3
ROT_SPEED = 0.15

# Texture Settings
#TEXTURE_SIZE = 64  # 64x64 pixels
#TEXTURE_SIZE = 256  # 256x256 pixels
TEXTURE_SIZE = 512  # 512x512 pixels
#OBS: Loading 1024x1024 texture maps currently does not work
#TEXTURE_SIZE = 1024  # 1024x1024 pixels
TEXTURE_INTENSITY = 1.2  # Texture intensity factor (1.0 = normal, <1.0 = darker, >1.0 = brighter)

# NOTE: Wall2 is currently not used
TEXTURE_THEMES = {
    "classic": {
        "wall1": "texture20.png",
        "wall2": "texture20.png",
        "floor": "texture28.png",
        "ceiling": "texture38.png"
    },
       
    "dungeon": {
        "wall1": "texture41.png",
        "wall2": "texture41.png",
        "floor": "texture40.png",
        "ceiling": "texture39.png"
    }
}    

class DOOMHouse:
    def __init__(self):
        self.window_name = "DOOMHouse - ClickHouse SQL Game Engine"
        
        # Tkinter Setup
        self.root = tk.Tk()
        self.root.title(self.window_name)
        self.root.geometry("640x540")
        self.root.resizable(False, False)
        self.root.configure(bg="black")
        
        self.label = tk.Label(self.root, bg="black")
        self.label.pack()

        # Status Label at the bottom (Multi-line)
        self.status_label = tk.Label(
            self.root,
            text="",
            bg="black",
            fg="#00FF00",
            font=("Courier", 11, "bold"),
            justify=tk.LEFT,
            anchor="w",
            padx=10,
            pady=5
        )
        self.status_label.pack(side=tk.BOTTOM, fill=tk.X)
        
        # Key State Tracking
        self.keys_pressed = set()
        self.root.bind("<KeyPress>", self._on_key_press)
        self.root.bind("<KeyRelease>", self._on_key_release)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Initial Player State (Defaults, may be overridden by WAD)
        self.pos_x = 6.5
        self.pos_y = 6.5
        self.dir_x = -1.0
        self.dir_y = 0.0
        self.plane_x = 0.0
        self.plane_y = 0.66

        # Connect to DB
        try:
            if USE_CHDB:
                print("🔗 Connecting to chDB (In-Process)...")
                self.db_client = chdb.session.Session()
                
                # Tune chDB for real-time performance
                self.db_client.query("SET async_insert = 0")
                self.db_client.query("SET wait_for_async_insert = 1")
                self.db_client.query("SET max_threads = 8")
                self.db_client.query("SET optimize_move_to_prewhere = 1")
                
                self.db_client.query("CREATE DATABASE IF NOT EXISTS doomhouse")
            else:
                print(f"🔗 Connecting to ClickHouse Server at {HOST}:{PORT}...")
                self.db_client = clickhouse_connect.get_client(
                    host=HOST, port=PORT, username=USER, password=PASS
                )
                self.db_client.command("CREATE DATABASE IF NOT EXISTS doomhouse")

            self.cleanup_database()
            self.initialize_game_data()
            
            # Theme selection
            self.theme_names = list(TEXTURE_THEMES.keys())
            self.current_theme_idx = 0
            self.current_theme = self.theme_names[self.current_theme_idx]
            
            self.initialize_texture()
            self.initialize_tables()
        except Exception as e:
            print(f"Error initializing database: {e}")
            sys.exit(1)

        # Frame tracking
        self.frame_id = 0

        # GUI Setup
        self.running = True
        self.in_splash = True

        # Performance Tracking
        self.total_insert_time = 0.0
        self.insert_count = 0
        self.total_select_time = 0.0
        self.select_count = 0
                
        # Show Splash Screen
        self.show_splash()

    def show_splash(self):
        splash_path = os.path.join("images", "splash.png")
        if os.path.exists(splash_path):
            try:
                with Image.open(splash_path) as img:
                    img = img.convert("RGB")
                    img = img.resize((640, 480), Image.LANCZOS)
                    
                    # Add text
                    draw = ImageDraw.Draw(img)
                    text = "Press any key to start"
                    
                    # Try to load a bigger font
                    font = None
                    font_paths = [
                        "/System/Library/Fonts/Supplemental/Arial.ttf",
                        "/Library/Fonts/Arial.ttf",
                        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
                    ]
                    for path in font_paths:
                        if os.path.exists(path):
                            try:
                                font = ImageFont.truetype(path, 30)
                                break
                            except:
                                continue
                    
                    if font is None:
                        font = ImageFont.load_default()

                    # Center text
                    try:
                        # Pillow >= 8.0.0
                        left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
                        w, h = right - left, bottom - top
                    except AttributeError:
                        # Fallback for older Pillow
                        w, h = draw.textsize(text, font=font)
                    
                    x = (640 - w) / 2
                    y = 400
                    
                    # Draw shadow for visibility
                    draw.text((x+2, y+2), text, fill=(0, 0, 0), font=font)
                    # Draw main text
                    draw.text((x, y), text, fill=(255, 255, 255), font=font)
                    
                    # Convert PIL to ImageTk
                    self.photo = ImageTk.PhotoImage(img)
                    self.label.config(image=self.photo)
                    self.root.update_idletasks()
            except Exception as e:
                print(f"Error loading splash screen: {e}")

    def start_game(self):
        if not self.in_splash:
            return
        self.in_splash = False
        # Initial Input to ensure a frame exists
        self.push_input(self.pos_x, self.pos_y)

    def _on_key_press(self, event):
        key = event.keysym.lower()
        self.keys_pressed.add(key)
        if self.in_splash:
            self.start_game()
        
        # Theme switching
        if key == 't':
            self.switch_theme()

    def _on_key_release(self, event):
        key = event.keysym.lower()
        self.keys_pressed.discard(key)

    def _on_close(self):
        self.running = False
        self.root.destroy()

    def load_texture(self, filename):
        if not os.path.exists(filename):
            print(f"⚠️ Warning: '{filename}' not found. Using fallback gray noise.")
            fallback = [(100, 100, 100) for _ in range(TEXTURE_SIZE**2)]
            return fallback

        print(f"🎨 Loading '{filename}' for database initialization...")
        try:
            with Image.open(filename) as img:
                img = img.convert("RGB")
                img = img.resize((TEXTURE_SIZE, TEXTURE_SIZE), Image.NEAREST)
                pixels = list(img.getdata())
                return pixels
        except Exception as e:
            print(f"Error processing texture: {e}")
            sys.exit(1)

    def _setup_texture_resource(self, table_name, dict_name, texture_file):
        """Helper to create table, dictionary and load texture data."""
        engine = "Memory" if USE_CHDB else "MergeTree ORDER BY id"
        
        # Map internal dictionary names to the ones expected by the BSP renderer
        # The BSP renderer expects 'dict_tex_wall', 'dict_tex_floor_data', 'dict_tex_ceiling_data'
        bsp_dict_map = {
            "dict_tex_wall1_data": "dict_tex_wall",
            "dict_tex_wall2_data": "dict_tex_wall2", # Not used yet but for consistency
            "dict_tex_floor_data": "dict_tex_floor_data",
            "dict_tex_ceiling_data": "dict_tex_ceiling_data"
        }
        
        target_dict_name = bsp_dict_map.get(dict_name, dict_name)
        
        try:
            self._db_command(f"DROP DICTIONARY IF EXISTS doomhouse.{target_dict_name}")
            self._db_command(f"DROP TABLE IF EXISTS doomhouse.{table_name}")
            self._db_command(f"""
                CREATE TABLE doomhouse.{table_name} (
                    id UInt32,
                    r UInt8,
                    g UInt8,
                    b UInt8
                ) ENGINE = {engine}
            """)
            
            self._db_command(f"""
                CREATE DICTIONARY doomhouse.{target_dict_name} (
                    id UInt32,
                    r UInt8,
                    g UInt8,
                    b UInt8
                )
                PRIMARY KEY id
                SOURCE(CLICKHOUSE(TABLE '{table_name}' DB 'doomhouse'))
                LIFETIME(MIN 3600 MAX 3600)
                LAYOUT(FLAT())
            """)
        except Exception as e:
            print(f"Error creating texture table/dictionary {target_dict_name}: {e}")

        texture_path = os.path.join("textures", texture_file)
        tex_data = self.load_texture(texture_path)
        
        print(f"💾 Initializing doomhouse.{table_name} table with {len(tex_data)} pixels...")
        try:
            if USE_CHDB:
                self.db_client.query(f"TRUNCATE TABLE doomhouse.{table_name}")
                batch_size = 10000
                for i in range(0, len(tex_data), batch_size):
                    batch = tex_data[i:i+batch_size]
                    values = []
                    for j, (r, g, b) in enumerate(batch):
                        idx = i + j + 1
                        rv = max(0, min(255, int(r * TEXTURE_INTENSITY)))
                        gv = max(0, min(255, int(g * TEXTURE_INTENSITY)))
                        bv = max(0, min(255, int(b * TEXTURE_INTENSITY)))
                        values.append(f"({idx},{rv},{gv},{bv})")
                    insert_sql = f"INSERT INTO doomhouse.{table_name} (id, r, g, b) VALUES {','.join(values)}"
                    self.db_client.query(insert_sql)
            else:
                self.db_client.command(f"TRUNCATE TABLE doomhouse.{table_name}")
                data = [
                    [
                        i + 1,
                        max(0, min(255, int(r * TEXTURE_INTENSITY))),
                        max(0, min(255, int(g * TEXTURE_INTENSITY))),
                        max(0, min(255, int(b * TEXTURE_INTENSITY)))
                    ]
                    for i, (r, g, b) in enumerate(tex_data)
                ]
                self.db_client.insert(f'doomhouse.{table_name}', data)
            
            print(f"🔄 Reloading dictionary doomhouse.{target_dict_name}...")
            self._db_command(f"SYSTEM RELOAD DICTIONARY doomhouse.{target_dict_name}")
        except Exception as e:
            print(f"Error initializing texture {target_dict_name}: {e}")

    def _db_command(self, sql):
        """Unified command execution for both chDB and Server."""
        if USE_CHDB:
            return self.db_client.query(sql)
        else:
            return self.db_client.command(sql)

    def cleanup_database(self):
        print("🧹 Cleaning up existing database objects to avoid dependency errors...")
        try:
            # 1. Drop Materialized Views first
            self._db_command("DROP VIEW IF EXISTS doomhouse.render_materialized")
            self._db_command("DROP VIEW IF EXISTS doomhouse.post_process_materialized")
            self._db_command("DROP VIEW IF EXISTS doomhouse.player_state_mv")
            
            # 2. Drop Dictionaries
            dicts = [
                "dict_map_data", "dict_floor_dist", "dict_tex_data", "dict_tex_wall_data",
                "dict_tex_wall1_data", "dict_tex_wall2_data", "dict_tex_floor_data", "dict_tex_ceiling_data",
                "dict_tex_wall", "dict_bsp_segs", "dict_bsp_resolved"
            ]
            for d in dicts:
                self._db_command(f"DROP DICTIONARY IF EXISTS doomhouse.{d}")
                
            # 3. Drop Tables
            tables = [
                "map_source", "floor_dist_source", "tex_source", "tex_wall_source",
                "tex_wall1_source", "tex_wall2_source", "tex_floor_source", "tex_ceiling_source",
                "player_input", "player_input_raw", "player_state", "rendered_frame", "rendered_frame_post_processed",
                "bsp_source", "bsp_resolved",
                "wad_vertexes", "wad_sectors", "wad_sidedefs", "wad_linedefs", "wad_segs", "wad_things"
            ]
            for t in tables:
                self._db_command(f"DROP TABLE IF EXISTS doomhouse.{t}")
        except Exception as e:
            print(f"Note: Cleanup encountered an issue: {e}")

    def execute_sql_script(self, script_path):
        """Helper to execute a SQL script that may contain multiple statements."""
        if not os.path.exists(script_path):
            print(f"⚠️ Warning: SQL script '{script_path}' not found.")
            return
        
        with open(script_path, 'r') as f:
            content = f.read()
            
        # Split by semicolon
        statements = content.split(';')
        for stmt in statements:
            # Remove comments
            lines = stmt.split('\n')
            clean_lines = []
            in_block_comment = False
            for line in lines:
                if in_block_comment:
                    if '*/' in line:
                        in_block_comment = False
                        line = line.split('*/', 1)[1]
                    else:
                        continue
                
                if not in_block_comment:
                    if '/*' in line:
                        if '*/' in line:
                            import re
                            line = re.sub(r'/\*.*?\*/', '', line)
                        else:
                            in_block_comment = True
                            line = line.split('/*', 1)[0]
                    
                    if '--' in line:
                        line = line.split('--', 1)[0]
                    
                    if line.strip():
                        clean_lines.append(line)
            
            stmt = '\n'.join(clean_lines).strip()
            if not stmt:
                continue
            
            # Try to extract name for dropping
            name = None
            upper_stmt = stmt.upper()
            if "CREATE TABLE" in upper_stmt:
                parts = stmt.split()
                for i, p in enumerate(parts):
                    if p.upper() == "TABLE":
                        name = parts[i+1]
                        break
            elif "CREATE DICTIONARY" in upper_stmt:
                parts = stmt.split()
                for i, p in enumerate(parts):
                    if p.upper() == "DICTIONARY":
                        name = parts[i+1]
                        break
            elif "CREATE MATERIALIZED VIEW" in upper_stmt:
                parts = stmt.split()
                for i, p in enumerate(parts):
                    if p.upper() == "VIEW":
                        name = parts[i+1]
                        break
            
            if name:
                name = name.split('(')[0].strip()
                if "DICTIONARY" in upper_stmt:
                    self._db_command(f"DROP DICTIONARY IF EXISTS {name}")
                elif "VIEW" in upper_stmt:
                    self._db_command(f"DROP VIEW IF EXISTS {name}")
                else:
                    self._db_command(f"DROP TABLE IF EXISTS {name}")
            
            print(f"💾 Executing statement from {script_path}...")
            try:
                self._db_command(stmt)
            except Exception as e:
                print(f"Error executing statement: {e}")

    def load_playpal(self, f, lumps):
        if 'PLAYPAL' not in lumps:
            print("⚠️ Warning: PLAYPAL not found. Using grayscale palette.")
            return [(i, i, i) for i in range(256)]
        
        pos, size, _ = lumps['PLAYPAL']
        f.seek(pos)
        data = f.read(768) # Read first palette (256 * 3)
        palette = []
        for i in range(0, 768, 3):
            r, g, b = struct.unpack('BBB', data[i:i+3])
            palette.append((r, g, b))
        return palette

    def load_flats(self, f, lumps, lump_list, palette):
        if 'F_START' not in lumps or 'F_END' not in lumps:
            print("⚠️ Warning: F_START/F_END not found.")
            return [], []

        f_start_idx = lumps['F_START'][2]
        f_end_idx = lumps['F_END'][2]
        
        print(f"🎨 Loading Flats from index {f_start_idx} to {f_end_idx}...")
        
        texture_infos = []
        texture_pixels = []
        
        # Start ID for textures. Let's reserve 0.
        # Flats will be 1..N
        current_id = 1
        
        for i in range(f_start_idx + 1, f_end_idx):
            lump = lump_list[i]
            name = lump['name']
            if lump['size'] != 4096: # 64x64 = 4096 bytes
                continue
                
            f.seek(lump['pos'])
            data = f.read(4096)
            
            texture_infos.append((current_id, name, 64, 64, 'flat'))
            
            # Process pixels
            for y in range(64):
                for x in range(64):
                    color_idx = data[y * 64 + x]
                    r, g, b = palette[color_idx]
                    # Pack color: 0x00BBGGRR (Little Endian UInt32)
                    # R is lowest byte
                    packed_color = r | (g << 8) | (b << 16)
                    texture_pixels.append((current_id, x, y, packed_color))
            
            current_id += 1
            
        return texture_infos, texture_pixels

    def initialize_game_data(self):
        print("🎮 Initializing game data (map, floor distances, BSP segments)...")
        self.execute_sql_script("src/SQL/create_source_tables.sql")
        self.execute_sql_script("src/SQL/create_dictionaries.sql")
        self.execute_sql_script("src/SQL/create_wad_texture_tables.sql")
        
        wad_path = os.path.join("maps", "Doom1.WAD")
        if not os.path.exists(wad_path):
            print(f"⚠️ Warning: WAD file '{wad_path}' not found. Falling back to square room.")
            self._initialize_fallback_data()
            return

        print(f"📖 Loading level data from {wad_path}...")
        try:
            with open(wad_path, 'rb') as f:
                # 1. Read Header
                header = f.read(12)
                ident, num_lumps, dict_offset = struct.unpack('<4sII', header)
                ident = ident.decode('ascii').strip('\0')
                if ident not in ['IWAD', 'PWAD']:
                    raise ValueError(f"Invalid WAD identification: {ident}")

                # 2. Read Directory
                f.seek(dict_offset)
                lumps = {}
                lump_list = []
                for i in range(num_lumps):
                    entry = f.read(16)
                    pos, size, name = struct.unpack('<II8s', entry)
                    name = name.decode('ascii').strip('\0').upper()
                    lumps[name] = (pos, size, i)
                    lump_list.append({'name': name, 'pos': pos, 'size': size})

                # Load Palette
                palette = self.load_playpal(f, lumps)
                
                # Load Flats
                flat_infos, flat_pixels = self.load_flats(f, lumps, lump_list, palette)
                
                # Insert Texture Data
                print(f"💾 Inserting {len(flat_infos)} flats and {len(flat_pixels)} pixels...")
                
                def insert_rows(table, rows, columns):
                    if not rows: return
                    if USE_CHDB:
                        # Batch insert for performance
                        batch_size = 50000 # Increased batch size for pixels
                        for i in range(0, len(rows), batch_size):
                            batch = rows[i:i+batch_size]
                            # Format values based on type
                            values = []
                            for row in batch:
                                row_vals = []
                                for val in row:
                                    if isinstance(val, str):
                                        row_vals.append(f"'{val}'")
                                    else:
                                        row_vals.append(str(val))
                                values.append(f"({','.join(row_vals)})")
                            self.db_client.query(f"INSERT INTO doomhouse.{table} ({columns}) VALUES {','.join(values)}")
                    else:
                        # For server, we might need smaller batches or direct insert
                        batch_size = 50000
                        for i in range(0, len(rows), batch_size):
                            batch = rows[i:i+batch_size]
                            self.db_client.insert(f'doomhouse.{table}', batch)

                insert_rows('wad_texture_info', flat_infos, 'id, name, width, height, type')
                insert_rows('wad_texture_data', flat_pixels, 'tex_id, u, v, color')
                
                # Reload Dictionaries
                self._db_command("SYSTEM RELOAD DICTIONARY doomhouse.dict_wad_texture_name_to_id")
                self._db_command("SYSTEM RELOAD DICTIONARY doomhouse.dict_wad_texture_pixels")

                # Find all levels in the WAD
                level_pattern = re.compile(r'^(E\dM\d|MAP\d\d)$')
                all_levels = [l['name'] for l in lump_list if level_pattern.match(l['name'])]
                print(f"🗺️ Found {len(all_levels)} levels in WAD: {', '.join(all_levels)}")

                # 3. Find E1M1
                if 'E1M1' not in lumps:
                    raise ValueError("E1M1 not found in WAD")
                
                e1m1_idx = lumps['E1M1'][2]
                
                # Helper to get lump data by relative index
                def get_lump_by_rel(rel_idx):
                    target = lump_list[e1m1_idx + rel_idx]
                    f.seek(target['pos'])
                    return f.read(target['size'])

                # Doom Level Lump Order:
                # 0: NAME, 1: THINGS, 2: LINEDEFS, 3: SIDEDEFS, 4: VERTEXES, 5: SEGS, 
                # 6: SSECTORS, 7: NODES, 8: SECTORS, 9: REJECT, 10: BLOCKMAP
                
                # 4. Parse VERTEXES -> wad_vertexes
                print("  - Parsing VERTEXES...")
                vertex_data = get_lump_by_rel(4)
                vertex_rows = []
                for i in range(0, len(vertex_data), 4):
                    x, y = struct.unpack('<hh', vertex_data[i:i+4])
                    vertex_rows.append((len(vertex_rows), x, y)) # id, x, y

                # 5. Parse SECTORS -> wad_sectors
                print("  - Parsing SECTORS...")
                sector_data = get_lump_by_rel(8)
                sector_rows = []
                for i in range(0, len(sector_data), 26):
                    s = struct.unpack('<hh8s8shhh', sector_data[i:i+26])
                    floor_h, ceil_h = s[0], s[1]
                    floor_tex = s[2].decode('ascii').strip('\0').upper()
                    ceil_tex = s[3].decode('ascii').strip('\0').upper()
                    light, special, tag = s[4], s[5], s[6]
                    sector_rows.append((len(sector_rows), floor_h, ceil_h, floor_tex, ceil_tex, light, special, tag))

                # 6. Parse SIDEDEFS -> wad_sidedefs
                print("  - Parsing SIDEDEFS...")
                sidedef_data = get_lump_by_rel(3)
                sidedef_rows = []
                for i in range(0, len(sidedef_data), 30):
                    s = struct.unpack('<hh8s8s8sh', sidedef_data[i:i+30])
                    x_off, y_off = s[0], s[1]
                    upper = s[2].decode('ascii').strip('\0').upper()
                    lower = s[3].decode('ascii').strip('\0').upper()
                    middle = s[4].decode('ascii').strip('\0').upper()
                    sector_id = s[5]
                    sidedef_rows.append((len(sidedef_rows), x_off, y_off, upper, lower, middle, sector_id))

                # 7. Parse LINEDEFS -> wad_linedefs
                print("  - Parsing LINEDEFS...")
                linedef_data = get_lump_by_rel(2)
                linedef_rows = []
                for i in range(0, len(linedef_data), 14):
                    s = struct.unpack('<hhhhhhh', linedef_data[i:i+14])
                    v1, v2, flags, special, tag, front, back = s
                    linedef_rows.append((len(linedef_rows), v1, v2, flags, special, tag, front, back))

                # 8. Parse THINGS -> wad_things (and set player start)
                print("  - Parsing THINGS...")
                thing_data = get_lump_by_rel(1)
                thing_rows = []
                for i in range(0, len(thing_data), 10):
                    x, y, angle, type_id, options = struct.unpack('<hhhhh', thing_data[i:i+10])
                    thing_rows.append((len(thing_rows), x, y, angle, type_id, options))
                    
                    if type_id == 1: # Player 1 Start
                        self.pos_x = x * 0.01
                        self.pos_y = y * 0.01
                        rad = math.radians(angle)
                        self.dir_x = math.cos(rad)
                        self.dir_y = math.sin(rad)
                        self.plane_x = -math.sin(rad) * 0.66
                        self.plane_y = math.cos(rad) * 0.66
                        print(f"  📍 Player 1 Start: ({self.pos_x:.2f}, {self.pos_y:.2f}) at {angle}°")

                # 9. Parse SEGS -> wad_segs
                print("  - Parsing SEGS...")
                seg_data = get_lump_by_rel(5)
                seg_rows = []
                for i in range(0, len(seg_data), 12):
                    v1, v2, angle, linedef_id, side, offset = struct.unpack('<hhhhhh', seg_data[i:i+12])
                    seg_rows.append((len(seg_rows), v1, v2, angle, linedef_id, side, offset))

                # 10. Insert into DB
                print("📐 Populating WAD tables into ClickHouse...")
                
                # Re-define insert_rows here to use the one defined above or just use the one above?
                # The one above is inside initialize_game_data scope, so it's fine.
                # But I need to make sure I don't shadow it or duplicate logic unnecessarily.
                # I'll just reuse the logic.
                
                insert_rows('wad_vertexes', vertex_rows, 'id, x, y')
                insert_rows('wad_sectors', sector_rows, 'id, floor_h, ceil_h, floor_tex, ceil_tex, light, special, tag')
                insert_rows('wad_sidedefs', sidedef_rows, 'id, x_off, y_off, upper, lower, middle, sector_id')
                insert_rows('wad_linedefs', linedef_rows, 'id, v1, v2, flags, special, tag, front_side, back_side')
                insert_rows('wad_things', thing_rows, 'id, x, y, angle, type, options')
                insert_rows('wad_segs', seg_rows, 'id, v1, v2, angle, linedef_id, side, offset')

                # 11. Resolve Geometry
                print("🔄 Resolving geometry (SEGS -> BSP Resolved)...")
                self.execute_sql_script("src/SQL/resolve_geometry.sql")
                
                self._db_command("SYSTEM RELOAD DICTIONARY doomhouse.dict_bsp_resolved")
                print("✅ Level data loaded and resolved successfully.")

        except Exception as e:
            print(f"❌ Error loading WAD data: {e}")
            import traceback
            traceback.print_exc()
            self._initialize_fallback_data()

    def _initialize_fallback_data(self):
        """Populate BSP segments with a simple square room as fallback."""
        print("📐 Populating fallback BSP segments...")
        # id, x1, y1, x2, y2, ceil, floor, wall_tex, ceil_tex, floor_tex, wall_tex_id, ceil_tex_id, floor_tex_id, light, sector_id, seg_offset, tex_x_off, tex_y_off, length
        segments = [
            [1, 1.0, 1.0, 8.0, 1.0, 1.0, 0.0, 'WALL', 'CEIL', 'FLOOR', 1, 1, 1, 200, 1, 0.0, 0.0, 0.0, 7.0],
            [2, 8.0, 1.0, 8.0, 8.0, 1.0, 0.0, 'WALL', 'CEIL', 'FLOOR', 1, 1, 1, 200, 1, 0.0, 0.0, 0.0, 7.0],
            [3, 8.0, 8.0, 1.0, 8.0, 1.0, 0.0, 'WALL', 'CEIL', 'FLOOR', 1, 1, 1, 200, 1, 0.0, 0.0, 0.0, 7.0],
            [4, 1.0, 8.0, 1.0, 1.0, 1.0, 0.0, 'WALL', 'CEIL', 'FLOOR', 1, 1, 1, 200, 1, 0.0, 0.0, 0.0, 7.0]
        ]
        
        columns = "id, x1, y1, x2, y2, ceil, floor, wall_tex, ceil_tex, floor_tex, wall_tex_id, ceil_tex_id, floor_tex_id, light, sector_id, seg_offset, tex_x_off, tex_y_off, length"
        
        try:
            if USE_CHDB:
                values = []
                for s in segments:
                    row = []
                    for val in s:
                        if isinstance(val, str):
                            row.append(f"'{val}'")
                        else:
                            row.append(str(val))
                    values.append(f"({','.join(row)})")
                self.db_client.query(f"INSERT INTO doomhouse.bsp_resolved ({columns}) VALUES {','.join(values)}")
            else:
                self.db_client.insert('doomhouse.bsp_resolved', segments)
            
            self._db_command("SYSTEM RELOAD DICTIONARY doomhouse.dict_bsp_resolved")
        except Exception as e:
            print(f"Error populating fallback BSP segments: {e}")

    def initialize_tables(self):
        # Re-create tables to ensure schema matches
        sql_files = [
            "src/SQL/player_input_table.sql",
            "src/SQL/player_state_table.sql",
            "src/SQL/rendered_frame_table.sql",
            "src/SQL/rendered_frame_post_processed_table.sql",
            "src/SQL/player_state.sql",
            "src/SQL/render_view.sql",
            #"src/SQL/post_process_view.sql",
        ]
        
        for sql_file in sql_files:
            self.execute_sql_script(sql_file)

    def turn_right_logic(self):
        old_dir_x = self.dir_x
        self.dir_x = self.dir_x * math.cos(-ROT_SPEED) - self.dir_y * math.sin(-ROT_SPEED)
        self.dir_y = old_dir_x * math.sin(-ROT_SPEED) + self.dir_y * math.cos(-ROT_SPEED)
        old_plane_x = self.plane_x
        self.plane_x = self.plane_x * math.cos(-ROT_SPEED) - self.plane_y * math.sin(-ROT_SPEED)
        self.plane_y = old_plane_x * math.sin(-ROT_SPEED) + self.plane_y * math.cos(-ROT_SPEED)

    def turn_left_logic(self):
        old_dir_x = self.dir_x
        self.dir_x = self.dir_x * math.cos(ROT_SPEED) - self.dir_y * math.sin(ROT_SPEED)
        self.dir_y = old_dir_x * math.sin(ROT_SPEED) + self.dir_y * math.cos(ROT_SPEED)
        old_plane_x = self.plane_x
        self.plane_x = self.plane_x * math.cos(ROT_SPEED) - self.plane_y * math.sin(ROT_SPEED)
        self.plane_y = old_plane_x * math.sin(ROT_SPEED) + self.plane_y * math.cos(ROT_SPEED)

    def process_input(self):
        moved = False
        
        # Rotation
        if 'left' in self.keys_pressed or 'a' in self.keys_pressed:
            self.turn_left_logic()
            moved = True
        if 'right' in self.keys_pressed or 'd' in self.keys_pressed:
            self.turn_right_logic()
            moved = True
            
        # Movement
        tx, ty = self.pos_x, self.pos_y
        if 'up' in self.keys_pressed or 'w' in self.keys_pressed:
            tx += self.dir_x * MOVE_SPEED
            ty += self.dir_y * MOVE_SPEED
            moved = True
        if 'down' in self.keys_pressed or 's' in self.keys_pressed:
            tx -= self.dir_x * MOVE_SPEED
            ty -= self.dir_y * MOVE_SPEED
            moved = True
            
        if moved:
            self.push_input(tx, ty)

    def push_input(self, target_x, target_y):
        try:
            start_time = time.time()
            self.frame_id += 1
            # TRUNCATE to ensure only one row triggers the MV
            self._db_command("TRUNCATE TABLE doomhouse.player_input_raw")
            self._db_command(f"""
                INSERT INTO doomhouse.player_input_raw
                (frame_id, old_x, old_y, try_x, try_y, dir_x, dir_y, plane_x, plane_y, timestamp)
                VALUES ({self.frame_id}, {self.pos_x}, {self.pos_y}, {target_x}, {target_y},
                        {self.dir_x}, {self.dir_y}, {self.plane_x}, {self.plane_y}, now())
            """)            
            self.insert_time = (time.time() - start_time) * 1000 # in ms
            self.total_insert_time += self.insert_time
            self.insert_count += 1
            self.avg_insert_time = self.total_insert_time / self.insert_count
            print(f"Insert: {self.insert_time:.2f}ms (Avg: {self.avg_insert_time:.2f}ms)")

            self.render()
        except Exception as e:
            print(f"Input Error: {e}")

    def run(self):
        self.update_loop()
        self.root.mainloop()

    def update_loop(self):
        if not self.running:
            return
            
        if not self.in_splash:
            if 'escape' in self.keys_pressed:
                self._on_close()
                return
            self.process_input()
            
        self.root.after(16, self.update_loop) # ~60 FPS target for input check

    def render(self):
        try:
            start_time = time.time()
            
            # Wait for the frame to be processed by the Materialized View pipeline
            # We poll for a short time to ensure the MV has finished its work
            max_retries = 50 # Increased retries
            table = None
            
            for i in range(max_retries):
                if USE_CHDB:
                    # Pull rendered frame from the materialized table using Arrow for zero-copy
                    #result = self.db_client.query("SELECT pos_x, pos_y, image_data FROM doomhouse.rendered_frame_post_processed", "Arrow")
                    result = self.db_client.query("SELECT pos_x, pos_y, image_data FROM doomhouse.rendered_frame", "Arrow")
                    
                    # Use PyArrow to read the buffer without copying
                    import pyarrow as pa
                    try:
                        reader = pa.ipc.open_stream(result.bytes())
                        table = reader.read_all()
                    except:
                        try:
                            reader = pa.ipc.open_file(result.bytes())
                            table = reader.read_all()
                        except:
                            table = None
                    
                    if table and table.num_rows > 0:                        
                        break
                else:
                    # Server mode: use standard query
                    result = self.db_client.query("SELECT pos_x, pos_y, image_data FROM doomhouse.rendered_frame_post_processed")
                    if result.result_rows:
                        # Convert to a format we can use below
                        self.pos_x = result.result_rows[0][0]
                        self.pos_y = result.result_rows[0][1]
                        pixel_data = result.result_rows[0][2]
                        import array
                        raw_bytes = array.array('I', pixel_data).tobytes()
                        table = True # Signal success                        
                        break
                
                time.sleep(0.05) # Wait 50ms before retrying
            
            if not table:
                print("⚠️ Warning: No frame data returned from database.")
                # Debug: Check if intermediate tables have data
                if USE_CHDB:
                    try:
                        input_count = self.db_client.query("SELECT count() FROM doomhouse.player_input_raw").bytes().decode().strip()
                        state_count = self.db_client.query("SELECT count() FROM doomhouse.player_state").bytes().decode().strip()
                        frame_count = self.db_client.query("SELECT count() FROM doomhouse.rendered_frame").bytes().decode().strip()
                        print(f"DEBUG: input_raw={input_count}, state={state_count}, frame={frame_count}")
                    except Exception as e:
                        print(f"Debug Error: {e}")
                return

            if USE_CHDB:
                self.pos_x = table.column('pos_x')[0].as_py()
                self.pos_y = table.column('pos_y')[0].as_py()
                pixel_data_list = table.column('image_data')[0]
                import numpy as np
                pixel_np = pixel_data_list.values.to_numpy()
                raw_bytes = pixel_np.tobytes()

            # Calculate render time
            select_time = (time.time() - start_time) * 1000 # in ms
            self.total_select_time += select_time
            self.select_count += 1
            avg_select_time = self.total_select_time / self.select_count
            print(f"Select: {select_time:.2f}ms (Avg: {avg_select_time:.2f}ms)")

            # Create image from raw bytes (640x480)
            # "RGBX" means 4 bytes per pixel, where X is the 4th byte (0 in our case).
            image = Image.frombytes("RGB", (640, 480), raw_bytes, "raw", "RGBX")

            # Convert PIL to ImageTk
            self.photo = ImageTk.PhotoImage(image)
            self.label.config(image=self.photo)
            
            # Update status text (Multi-line)            
            fps = 1000/(self.insert_time + select_time)
            avgfps = 1000/(self.avg_insert_time + avg_select_time)
            line1 = f"{fps:2.1f}fps (avg: {avgfps:2.1f}fps) | Insert: {self.insert_time:3.2f}ms (avg: {self.avg_insert_time:3.2f}ms) | Select: {select_time:3.2f}ms (avg: {avg_select_time:3.2f}ms)"
            line2 = f"Pos: ({self.pos_x:5.2f}, {self.pos_y:5.2f}) | Theme: {self.current_theme.upper()} (Press 'T' to switch theme)"

            self.status_label.config(text=f"{line1}\n{line2}")
            
            self.root.update_idletasks()
        except Exception as e:
            print(f"Render Error: {e}")

    def switch_theme(self):
        self.current_theme_idx = (self.current_theme_idx + 1) % len(self.theme_names)
        self.current_theme = self.theme_names[self.current_theme_idx]
        print(f"🎭 Switching to theme: {self.current_theme}")
        self.initialize_texture()
        # Force a re-render
        self.push_input(self.pos_x, self.pos_y)

    def initialize_texture(self):
        theme = TEXTURE_THEMES[self.current_theme]
        print(f"🌟 Initializing textures for theme: {self.current_theme}")
        
        # Initialize Wall Textures
        self._setup_texture_resource("tex_wall1_source", "dict_tex_wall1_data", theme["wall1"])
        self._setup_texture_resource("tex_wall2_source", "dict_tex_wall2_data", theme["wall2"])
        
        # Initialize Floor Texture
        self._setup_texture_resource("tex_floor_source", "dict_tex_floor_data", theme["floor"])
        
        # Initialize Ceiling Texture
        self._setup_texture_resource("tex_ceiling_source", "dict_tex_ceiling_data", theme["ceiling"])

def main():
    app = DOOMHouse()
    app.run()

if __name__ == "__main__":
    main()
