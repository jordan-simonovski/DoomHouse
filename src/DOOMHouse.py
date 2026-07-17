import clickhouse_connect
import sys
import math
import os
import time
import threading
import warnings
from concurrent.futures import ThreadPoolExecutor
import tkinter as tk
import numpy as np

# np.fromstring(sep=',') is the fastest text->uint32 path (~4.6x faster than
# np.array(str.split(...)) on a full quarter, and it's on the per-frame hot path),
# but numpy deprecated the separated form. Silence that one warning; if a future
# numpy removes it, switch the parse in _handle_row to a binary decode.
warnings.filterwarnings("ignore", message="The binary mode of fromstring")
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

# Streaming: how often the server flushes streamed rows to the client. The
# server default is 7500ms; we drop it to ~one frame so each rendered frame is
# pushed the moment it lands instead of after a multi-second batch window.
STREAM_FLUSH_MS = int(os.getenv('STREAM_FLUSH_MS', '16'))
FRAME_W = 640
ROWS_PER_QUARTER = 120

# Movement Constants (per rendered frame). Streaming roughly tripled the frame
# rate versus the original polling loop, and movement is applied per frame, so
# these are scaled down to keep the original walking/turning feel. Tune to taste.
MOVE_SPEED = 0.12
ROT_SPEED = 0.06

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

        # Connect to DB
        try:
            self.client = clickhouse_connect.get_client(
                host=HOST, port=PORT, username=USER, password=PASS
            )

            # Get and print ClickHouse version
            version = self.client.query("SELECT version()").result_rows[0][0]
            print(f"Connected to ClickHouse version: {version}")

            # Version check: streaming queries (`SELECT ... STREAM` +
            # enable_streaming_queries) require ClickHouse 26.6 or later.
            try:
                v_parts = [int(p) for p in version.split('.')]
                required_v = [26, 6]
                is_supported = True
                for i in range(min(len(v_parts), len(required_v))):
                    if v_parts[i] < required_v[i]:
                        is_supported = False
                        break
                    elif v_parts[i] > required_v[i]:
                        break

                if not is_supported:
                    print("\n" + "="*80)
                    print("**OBS**: Streaming queries (SELECT ... STREAM) require ClickHouse 26.6 or later.")
                    print("="*80 + "\n")
            except Exception as ve:
                print(f"Could not parse ClickHouse version for compatibility check: {ve}")
            
            self.client.command("CREATE DATABASE IF NOT EXISTS doomhouse")
            self.cleanup_database()
            self.initialize_game_data()
            
            # Theme selection
            self.theme_names = list(TEXTURE_THEMES.keys())
            self.current_theme_idx = 0
            self.current_theme = self.theme_names[self.current_theme_idx]
            
            self.initialize_texture()
            self.initialize_tables()
        except Exception as e:
            print(f"Error connecting to ClickHouse: {e}")
            sys.exit(1)

        # Frame tracking
        self.frame_id = 0

        # Initial Player State
        self.pos_x = 3.5
        self.pos_y = 3.5
        self.dir_x = -1.0
        self.dir_y = 0.0
        self.plane_x = 0.0
        self.plane_y = 0.66

        # GUI Setup
        self.running = True
        self.in_splash = True

        # Performance Tracking
        self.total_insert_time = 0.0
        self.insert_count = 0
        self.insert_time = 0.0
        self.avg_insert_time = 0.0
        self.frames_painted = 0
        self.last_paint_time = time.time()
        self.paint_fps = 0.0

        # Streaming state: each quarter has its own long-lived STREAM query
        # running in a background thread. Workers write the latest quarter buffer
        # here; the Tk paint loop composites and displays them.
        self.quarter_data = [None, None, None, None]   # numpy uint32 pixels per quarter
        self.quarter_pos = [None, None, None, None]     # (pos_x, pos_y) per quarter
        self.quarter_frame = [None, None, None, None]   # frame_id per quarter (tearing barrier)
        self.frame_lock = threading.Lock()
        self.new_frame = False
        self.stream_error = None                        # last stream failure, surfaced on screen
        self.stream_threads = []
        self.start_streams()

        # Concurrent render dispatch: one client + thread per quarter so the four
        # renders run in parallel (see push_input). render_busy gates overlap.
        self.render_clients = [
            clickhouse_connect.get_client(host=HOST, port=PORT, username=USER, password=PASS)
            for _ in range(4)
        ]
        self.render_pool = ThreadPoolExecutor(max_workers=4)
        self.render_busy = False
        self._pending = 0
        self._pending_lock = threading.Lock()
        self._render_start = time.time()

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
        # Best-effort cleanup so we don't leave server sessions/threads dangling.
        try:
            self.render_pool.shutdown(wait=False)
        except Exception:
            pass
        for c in [self.client, *self.render_clients]:
            try:
                c.close()
            except Exception:
                pass
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
        try:
            self.client.command(f"DROP TABLE IF EXISTS doomhouse.{table_name}")
            self.client.command(f"""
                CREATE TABLE doomhouse.{table_name} (
                    id UInt32,
                    r UInt8,
                    g UInt8,
                    b UInt8
                ) ENGINE = MergeTree ORDER BY id
            """)
            
            self.client.command(f"DROP DICTIONARY IF EXISTS doomhouse.{dict_name}")
            self.client.command(f"""
                CREATE DICTIONARY doomhouse.{dict_name} (
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
            print(f"Error creating texture table/dictionary {dict_name}: {e}")

        texture_path = os.path.join("textures", texture_file)
        tex_data = self.load_texture(texture_path)
        
        print(f"💾 Initializing doomhouse.{table_name} table with {len(tex_data)} pixels...")
        try:
            self.client.command(f"TRUNCATE TABLE doomhouse.{table_name}")
            data = [
                [
                    i + 1,
                    max(0, min(255, int(r * TEXTURE_INTENSITY))),
                    max(0, min(255, int(g * TEXTURE_INTENSITY))),
                    max(0, min(255, int(b * TEXTURE_INTENSITY)))
                ]
                for i, (r, g, b) in enumerate(tex_data)
            ]
            self.client.insert(f'doomhouse.{table_name}', data)
            
            print(f"🔄 Reloading dictionary doomhouse.{dict_name}...")
            self.client.command(f"SYSTEM RELOAD DICTIONARY doomhouse.{dict_name}")
        except Exception as e:
            print(f"Error initializing texture {dict_name}: {e}")

    def switch_theme(self):
        self.current_theme_idx = (self.current_theme_idx + 1) % len(self.theme_names)
        self.current_theme = self.theme_names[self.current_theme_idx]
        print(f"🎭 Switching to theme: {self.current_theme}")
        self.initialize_texture()
        # We don't necessarily need to re-initialize tables, but we might need to reload the view
        # if we change how it references dictionaries. For now, let's just reload textures.
        # Actually, if we use the same dictionary names, we just need to reload them.
        self.push_input(self.pos_x, self.pos_y) # Force a re-render

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

    def cleanup_database(self):
        print("🧹 Cleaning up existing database objects to avoid dependency errors...")
        try:
            # 1. Drop Materialized Views first
            self.client.command("DROP VIEW IF EXISTS doomhouse.render_materialized")
            self.client.command("DROP VIEW IF EXISTS doomhouse.post_process_materialized")
            self.client.command("DROP VIEW IF EXISTS doomhouse.render_materialized_top")
            self.client.command("DROP VIEW IF EXISTS doomhouse.render_materialized_bottom")
            self.client.command("DROP VIEW IF EXISTS doomhouse.post_process_materialized_top")
            self.client.command("DROP VIEW IF EXISTS doomhouse.post_process_materialized_bottom")
            for i in range(1, 5):
                self.client.command(f"DROP VIEW IF EXISTS doomhouse.render_materialized_{i}")
                self.client.command(f"DROP VIEW IF EXISTS doomhouse.post_process_materialized_{i}")

            # 2. Drop Dictionaries
            dicts = [
                "dict_map_data", "dict_floor_dist", "dict_tex_data", "dict_tex_wall_data",
                "dict_tex_wall1_data", "dict_tex_wall2_data", "dict_tex_floor_data", "dict_tex_ceiling_data"
            ]
            for d in dicts:
                self.client.command(f"DROP DICTIONARY IF EXISTS doomhouse.{d}")
                
            # 3. Drop Tables
            tables = [
                "map_source", "floor_dist_source", "tex_source", "tex_wall_source",
                "tex_wall1_source", "tex_wall2_source", "tex_floor_source", "tex_ceiling_source",
                "player_input", "rendered_frame", "rendered_frame_post_processed",
                "rendered_frame_top", "rendered_frame_bottom",
                "rendered_frame_post_processed_top", "rendered_frame_post_processed_bottom"
            ]
            for i in range(1, 5):
                tables.append(f"player_input_{i}")
            for t in tables:
                self.client.command(f"DROP TABLE IF EXISTS doomhouse.{t}")
            for i in range(1, 5):
                self.client.command(f"DROP TABLE IF EXISTS doomhouse.rendered_frame_{i}")
                self.client.command(f"DROP TABLE IF EXISTS doomhouse.rendered_frame_post_processed_{i}")
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
                    self.client.command(f"DROP DICTIONARY IF EXISTS {name}")
                elif "VIEW" in upper_stmt:
                    self.client.command(f"DROP VIEW IF EXISTS {name}")
                else:
                    self.client.command(f"DROP TABLE IF EXISTS {name}")
            
            print(f"💾 Executing statement from {script_path}...")
            try:
                self.client.command(stmt)
            except Exception as e:
                print(f"Error executing statement: {e}")

    def initialize_game_data(self):
        print("🎮 Initializing game data (map, floor distances)...")
        self.execute_sql_script("src/SQL/create_source_tables.sql")
        self.execute_sql_script("src/SQL/create_dictionaries.sql")

    def initialize_tables(self):
        # Only the streamed bus tables are persistent objects now. The render
        # itself is a set of query templates the client fills per frame and
        # dispatches concurrently (see load_frame_templates / push_input).
        self.execute_sql_script("src/SQL/rendered_frame_post_processed_table.sql")
        self.load_frame_templates()

    def load_frame_templates(self):
        # Four render+blur query templates with @@...@@ placeholders for the
        # current player input, delimited by '-- QUARTER' lines.
        import re
        with open("src/SQL/frame_render.sql") as f:
            content = f.read()
        # Split on delimiter lines of the exact form "-- QUARTER <n>" (the header
        # comment mentions the phrase, so match the numbered line specifically).
        chunks = re.split(r'(?m)^-- QUARTER \d+\s*$', content)
        self.frame_templates = [c.strip() for c in chunks[1:] if c.strip()]
        if len(self.frame_templates) != 4:
            raise RuntimeError(f"expected 4 frame templates, got {len(self.frame_templates)}")

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
        # Fire the four quarter renders concurrently. Each quarter is a render+blur
        # query template with the current input inlined as literals, dispatched on
        # its own client/thread, so the four renders run in parallel across cores
        # (~20ms) instead of one INSERT rendering them serially.
        #
        # Non-blocking: we don't wait for the renders here (the frames come back
        # over the STREAM queries and are drawn by the paint loop). render_busy
        # skips input while a render is in flight, so we never queue faster than
        # the pipeline can render and the client always shows the latest frame.
        if self.render_busy:
            return
        self.render_busy = True
        self.frame_id += 1
        subs = {
            "@@frame_id@@": str(self.frame_id),
            "@@old_x@@": repr(self.pos_x), "@@old_y@@": repr(self.pos_y),
            "@@try_x@@": repr(target_x), "@@try_y@@": repr(target_y),
            "@@dir_x@@": repr(self.dir_x), "@@dir_y@@": repr(self.dir_y),
            "@@plane_x@@": repr(self.plane_x), "@@plane_y@@": repr(self.plane_y),
        }
        self._render_start = time.time()
        self._pending = 4
        # Submit under try/except: if the pool rejects a submit partway through
        # (e.g. shut down during teardown), settle the un-dispatched quarters so
        # _pending still reaches 0 and render_busy is released — otherwise the
        # gate sticks True and input freezes permanently.
        for i in range(4):
            try:
                fut = self.render_pool.submit(self._insert_quarter, i, subs)
            except Exception as e:
                print(f"Render submit failed for quarter {i + 1}: {e}")
                self._on_quarter_done(None)
                continue
            fut.add_done_callback(self._on_quarter_done)

    def _insert_quarter(self, idx, subs):
        q = idx + 1
        query = self.frame_templates[idx]
        for k, v in subs.items():
            query = query.replace(k, v)
        if "@@" in query:
            # A placeholder went unsubstituted — fail loudly rather than sending
            # broken SQL that ClickHouse rejects with a confusing parse error.
            raise ValueError(f"unsubstituted placeholder in quarter {q} template")
        self.render_clients[idx].command(
            f"INSERT INTO doomhouse.rendered_frame_post_processed_{q} "
            f"(frame_id, pos_x, pos_y, image_data) {query}"
        )

    def _on_quarter_done(self, fut):
        err = fut.exception() if fut is not None else None
        if err:
            # Surface render failures on screen too — unlike stream errors these
            # otherwise only hit the console, so a broken render looks like a hang.
            msg = str(err).split('\n')[0]
            print(f"Render dispatch error: {msg}")
            self.stream_error = f"Render: {msg}"
        with self._pending_lock:
            self._pending -= 1
            done = self._pending == 0
        if done:
            self.insert_time = (time.time() - self._render_start) * 1000
            self.total_insert_time += self.insert_time
            self.insert_count += 1
            self.avg_insert_time = self.total_insert_time / self.insert_count
            self.render_busy = False

    def run(self):
        self.update_loop()
        self.paint_loop()
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

    def start_streams(self):
        """Open one long-lived STREAM query per quarter in a background thread.

        Instead of polling the four frame tables after every input, each worker
        subscribes once with `SELECT ... STREAM` and blocks on the connection.
        The moment the render pipeline inserts a new frame row, ClickHouse pushes
        it down the open connection and the worker parses it. This removes the
        per-frame query round-trip and lets the display update as frames arrive.
        """
        for i in range(4):
            t = threading.Thread(target=self._stream_worker, args=(i,), daemon=True)
            t.start()
            self.stream_threads.append(t)

    def _stream_worker(self, idx):
        quarter = idx + 1
        # We stream the pixel array as a comma-joined string in a text format.
        # Binary formats (RowBinary/Native/Arrow) buffer the payload server-side
        # and never flush a single big row; row-based text formats flush live.
        # WHERE ts >= now() so a mid-game reconnect tails only new frames instead
        # of replaying the TTL window of buffered rows (which would flood the
        # client and rewind the player to a stale streamed position).
        query = (
            f"SELECT frame_id, pos_x, pos_y, arrayStringConcat(image_data, ',') "
            f"FROM doomhouse.rendered_frame_post_processed_{quarter} STREAM "
            f"WHERE ts >= now()"
        )
        settings = {
            'enable_streaming_queries': 1,
            'stream_flush_interval_ms': STREAM_FLUSH_MS,
        }
        while self.running:
            try:
                # compress=False is required: compression buffers the response
                # until a block fills, which defeats live streaming. One client per
                # reconnect attempt, always closed in finally so a flapping stream
                # doesn't leak connections/sockets.
                conn = clickhouse_connect.get_client(
                    host=HOST, port=PORT, username=USER, password=PASS, compress=False
                )
                try:
                    buf = bytearray()
                    with conn.raw_stream(query, settings=settings) as stream:
                        for chunk in stream:
                            if not self.running:
                                break
                            buf += chunk
                            # A stream flush may split or batch rows; parse every
                            # complete newline-terminated row we have so far.
                            nl = buf.find(b'\n')
                            while nl != -1:
                                line = bytes(buf[:nl])
                                del buf[:nl + 1]
                                self._handle_row(idx, line)
                                nl = buf.find(b'\n')
                finally:
                    conn.close()
            except Exception as e:
                if self.running:
                    msg = str(e).split('\n')[0]
                    print(f"Stream {quarter} error (reconnecting): {msg}")
                    # Surface it on screen so the game doesn't just hang on the
                    # splash with no explanation (e.g. a ClickHouse that predates
                    # STREAM, or nothing listening on the configured host/port).
                    self.stream_error = f"Quarter {quarter}: {msg}"
            # Backoff before any reconnect — covers both the error path and a
            # clean stream end, so a repeatedly-ending stream can't busy-loop.
            if self.running:
                time.sleep(0.5)

    def _handle_row(self, idx, line):
        if not line:
            return
        try:
            fid, px, py, pixels = line.split(b'\t')
            # numpy parse is ~4x faster than array('I', map(int, ...)); less
            # wall-time per parse means the 4 stream threads block each other on
            # the GIL for less of the frame budget.
            vals = np.fromstring(pixels, dtype=np.uint32, sep=',')
        except Exception as e:
            print(f"Parse error on quarter {idx + 1}: {e}")
            return
        with self.frame_lock:
            self.quarter_data[idx] = vals
            self.quarter_pos[idx] = (float(px.decode()), float(py.decode()))
            self.quarter_frame[idx] = int(fid)
            self.new_frame = True

    def paint_loop(self):
        """Composite the four latest quarter buffers and draw them.

        Runs on the Tk main thread (~60 Hz). It only redraws when a worker has
        delivered a fresh frame, so it is idle-cheap when the player isn't moving.
        """
        if not self.running:
            return
        try:
            # Frame barrier: only composite when all four quarters have arrived
            # AND carry the same frame_id. This stops tearing between adjacent
            # frames — a quarter from frame N+1 is never stitched onto frame N.
            # The check and the snapshot must be under one lock: a stream thread
            # can overwrite a quarter between an unlocked check and the copy,
            # which would tear exactly the frame the barrier is meant to protect.
            quarters = pos = None
            with self.frame_lock:
                if self.new_frame and all(q is not None for q in self.quarter_data) \
                        and len(set(self.quarter_frame)) == 1:
                    quarters = list(self.quarter_data)
                    pos = self.quarter_pos[0]
                    self.new_frame = False
            if quarters is not None:
                self._composite_and_draw(quarters, pos)
            elif self.frames_painted == 0 and self.stream_error:
                # No frame yet and a stream is failing — don't hang silently.
                self.status_label.config(
                    text=f"Waiting for frames — stream error:\n{self.stream_error}")
        except Exception as e:
            print(f"Paint error: {e}")
        self.root.after(16, self.paint_loop)

    def _composite_and_draw(self, quarters, pos):
        # Stitch the four partial buffers, slicing off the overlap rows that the
        # post-process blur needs for seamless quarter boundaries.
        # Q1: keep rows 0-119 | Q2/Q3: drop leading overlap row | Q4: drop leading overlap row
        row = FRAME_W
        span = ROWS_PER_QUARTER * row
        p1 = quarters[0][:span]
        p2 = quarters[1][row:row + span]
        p3 = quarters[2][row:row + span]
        p4 = quarters[3][row:]

        # Each UInt32 is [R, G, B, 0] in little-endian memory -> raw RGBX bytes.
        raw_bytes = np.concatenate((p1, p2, p3, p4)).tobytes()
        image = Image.frombytes("RGB", (640, 480), raw_bytes, "raw", "RGBX")

        self.photo = ImageTk.PhotoImage(image)
        self.label.config(image=self.photo)

        if pos is not None:
            self.pos_x, self.pos_y = pos

        # Measure the paint rate (frames actually shown per second).
        now = time.time()
        dt = now - self.last_paint_time
        self.last_paint_time = now
        if dt > 0:
            self.paint_fps = 0.9 * self.paint_fps + 0.1 * (1.0 / dt) if self.frames_painted else 1.0 / dt
        self.frames_painted += 1

        line1 = (f"{self.paint_fps:2.1f}fps (streamed) | "
                 f"Insert: {self.insert_time:3.2f}ms (avg: {self.avg_insert_time:3.2f}ms) | "
                 f"Frames: {self.frames_painted}")
        line2 = f"Pos: ({self.pos_x:5.2f}, {self.pos_y:5.2f}) | Theme: {self.current_theme.upper()} (Press 'T' to switch theme)"
        self.status_label.config(text=f"{line1}\n{line2}")

def main():
    app = DOOMHouse()
    app.run()

if __name__ == "__main__":
    main()
