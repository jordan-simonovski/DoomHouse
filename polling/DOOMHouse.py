import clickhouse_connect
import sys
import math
import os
import time
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageTk
from dotenv import load_dotenv

# ============================================================================
#  POLLING variant — fair like-for-like comparison for the streaming version.
#
#  This uses the SAME concurrent render engine as src/ (the four per-quarter
#  render+blur query templates in polling/SQL/frame_render.sql, dispatched four
#  at a time), but delivers frames via request/response: after dispatching the
#  four renders it SELECTs the results back and paints, instead of tailing them
#  over a STREAM. So the difference between this and src/ isolates exactly what
#  streaming delivery buys; the difference between this and non-streaming/ (the
#  original sequential materialized-view engine) isolates the render concurrency.
#
#  Runs on its own database (doomhouse_poll) so all three can run at once.
# ============================================================================

load_dotenv()

HOST = os.getenv('CLICKHOUSE_HOST', 'localhost')
PORT = int(os.getenv('CLICKHOUSE_PORT', '8123'))
USER = os.getenv('CLICKHOUSE_USER', 'default')
PASS = os.getenv('CLICKHOUSE_PASS', '')

DB = "doomhouse_poll"
FRAME_W = 640
ROWS_PER_QUARTER = 120

# Same per-frame movement constants as the streaming version, so walking/turning
# speed is comparable at comparable frame rates.
MOVE_SPEED = 0.12
ROT_SPEED = 0.06

TEXTURE_SIZE = 512
TEXTURE_INTENSITY = 1.2

TEXTURE_THEMES = {
    "classic": {"wall1": "texture20.png", "wall2": "texture20.png",
                "floor": "texture28.png", "ceiling": "texture38.png"},
    "dungeon": {"wall1": "texture41.png", "wall2": "texture41.png",
                "floor": "texture40.png", "ceiling": "texture39.png"},
}


class DOOMHouse:
    def __init__(self):
        self.window_name = "DOOMHouse (POLLING - concurrent render) - ClickHouse SQL Game Engine"

        self.root = tk.Tk()
        self.root.title(self.window_name)
        self.root.geometry("640x540")
        self.root.resizable(False, False)
        self.root.configure(bg="black")

        self.label = tk.Label(self.root, bg="black")
        self.label.pack()

        self.status_label = tk.Label(
            self.root, text="", bg="black", fg="#00FF00",
            font=("Courier", 11, "bold"), justify=tk.LEFT, anchor="w", padx=10, pady=5,
        )
        self.status_label.pack(side=tk.BOTTOM, fill=tk.X)

        self.keys_pressed = set()
        self.root.bind("<KeyPress>", self._on_key_press)
        self.root.bind("<KeyRelease>", self._on_key_release)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        try:
            self.client = clickhouse_connect.get_client(host=HOST, port=PORT, username=USER, password=PASS)
            version = self.client.query("SELECT version()").result_rows[0][0]
            print(f"Connected to ClickHouse version: {version}")

            self.client.command(f"CREATE DATABASE IF NOT EXISTS {DB}")
            self.cleanup_database()
            self.initialize_game_data()

            self.theme_names = list(TEXTURE_THEMES.keys())
            self.current_theme_idx = 0
            self.current_theme = self.theme_names[self.current_theme_idx]

            self.initialize_texture()
            self.load_frame_templates()

            # One client per quarter for concurrent render SELECTs.
            self.render_clients = [
                clickhouse_connect.get_client(host=HOST, port=PORT, username=USER, password=PASS)
                for _ in range(4)
            ]
            self.render_pool = ThreadPoolExecutor(max_workers=4)
        except Exception as e:
            print(f"Error connecting to ClickHouse: {e}")
            sys.exit(1)

        self.frame_id = 0
        self.pos_x, self.pos_y = 3.5, 3.5
        self.dir_x, self.dir_y = -1.0, 0.0
        self.plane_x, self.plane_y = 0.0, 0.66

        self.running = True
        self.in_splash = True
        self.rendering = False

        self.total_render_time = 0.0
        self.render_count = 0
        self.render_time = 0.0
        self.frames_painted = 0
        self.last_paint_time = time.time()
        self.paint_fps = 0.0

        self.show_splash()

    def show_splash(self):
        splash_path = os.path.join("images", "splash.png")
        if not os.path.exists(splash_path):
            return
        try:
            with Image.open(splash_path) as img:
                img = img.convert("RGB").resize((640, 480), Image.LANCZOS)
                draw = ImageDraw.Draw(img)
                text = "Press any key to start (POLLING)"
                font = None
                for path in ["/System/Library/Fonts/Supplemental/Arial.ttf",
                             "/Library/Fonts/Arial.ttf",
                             "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]:
                    if os.path.exists(path):
                        try:
                            font = ImageFont.truetype(path, 30); break
                        except Exception:
                            continue
                if font is None:
                    font = ImageFont.load_default()
                try:
                    l, t, r, b = draw.textbbox((0, 0), text, font=font)
                    w = r - l
                except AttributeError:
                    w, _ = draw.textsize(text, font=font)
                x, y = (640 - w) / 2, 400
                draw.text((x + 2, y + 2), text, fill=(0, 0, 0), font=font)
                draw.text((x, y), text, fill=(255, 255, 255), font=font)
                self.photo = ImageTk.PhotoImage(img)
                self.label.config(image=self.photo)
                self.root.update_idletasks()
        except Exception as e:
            print(f"Error loading splash screen: {e}")

    def start_game(self):
        if not self.in_splash:
            return
        self.in_splash = False
        self.render_and_paint(self.pos_x, self.pos_y)

    def _on_key_press(self, event):
        key = event.keysym.lower()
        self.keys_pressed.add(key)
        if self.in_splash:
            self.start_game()
        if key == 't':
            self.switch_theme()

    def _on_key_release(self, event):
        self.keys_pressed.discard(event.keysym.lower())

    def _on_close(self):
        self.running = False
        try:
            self.render_pool.shutdown(wait=False)
        except Exception:
            pass
        for c in [self.client, *getattr(self, "render_clients", [])]:
            try:
                c.close()
            except Exception:
                pass
        self.root.destroy()

    def load_texture(self, filename):
        if not os.path.exists(filename):
            print(f"⚠️ Warning: '{filename}' not found. Using fallback gray noise.")
            return [(100, 100, 100) for _ in range(TEXTURE_SIZE ** 2)]
        print(f"🎨 Loading '{filename}'...")
        try:
            with Image.open(filename) as img:
                img = img.convert("RGB").resize((TEXTURE_SIZE, TEXTURE_SIZE), Image.NEAREST)
                return list(img.getdata())
        except Exception as e:
            print(f"Error processing texture: {e}")
            sys.exit(1)

    def _setup_texture_resource(self, table_name, dict_name, texture_file):
        try:
            self.client.command(f"DROP TABLE IF EXISTS {DB}.{table_name}")
            self.client.command(
                f"CREATE TABLE {DB}.{table_name} (id UInt32, r UInt8, g UInt8, b UInt8) "
                f"ENGINE = MergeTree ORDER BY id"
            )
            self.client.command(f"DROP DICTIONARY IF EXISTS {DB}.{dict_name}")
            self.client.command(
                f"CREATE DICTIONARY {DB}.{dict_name} (id UInt32, r UInt8, g UInt8, b UInt8) "
                f"PRIMARY KEY id SOURCE(CLICKHOUSE(TABLE '{table_name}' DB '{DB}')) "
                f"LIFETIME(MIN 3600 MAX 3600) LAYOUT(FLAT())"
            )
        except Exception as e:
            print(f"Error creating texture table/dictionary {dict_name}: {e}")

        tex_data = self.load_texture(os.path.join("textures", texture_file))
        try:
            self.client.command(f"TRUNCATE TABLE {DB}.{table_name}")
            data = [[i + 1,
                     max(0, min(255, int(r * TEXTURE_INTENSITY))),
                     max(0, min(255, int(g * TEXTURE_INTENSITY))),
                     max(0, min(255, int(b * TEXTURE_INTENSITY)))]
                    for i, (r, g, b) in enumerate(tex_data)]
            self.client.insert(f'{DB}.{table_name}', data)
            self.client.command(f"SYSTEM RELOAD DICTIONARY {DB}.{dict_name}")
        except Exception as e:
            print(f"Error initializing texture {dict_name}: {e}")

    def switch_theme(self):
        self.current_theme_idx = (self.current_theme_idx + 1) % len(self.theme_names)
        self.current_theme = self.theme_names[self.current_theme_idx]
        print(f"🎭 Switching to theme: {self.current_theme}")
        self.initialize_texture()
        self.render_and_paint(self.pos_x, self.pos_y)

    def initialize_texture(self):
        theme = TEXTURE_THEMES[self.current_theme]
        print(f"🌟 Initializing textures for theme: {self.current_theme}")
        self._setup_texture_resource("tex_wall1_source", "dict_tex_wall1_data", theme["wall1"])
        self._setup_texture_resource("tex_wall2_source", "dict_tex_wall2_data", theme["wall2"])
        self._setup_texture_resource("tex_floor_source", "dict_tex_floor_data", theme["floor"])
        self._setup_texture_resource("tex_ceiling_source", "dict_tex_ceiling_data", theme["ceiling"])

    def cleanup_database(self):
        print("🧹 Cleaning up existing database objects...")
        try:
            for d in ["dict_map_data", "dict_floor_dist", "dict_tex_wall1_data",
                      "dict_tex_wall2_data", "dict_tex_floor_data", "dict_tex_ceiling_data"]:
                self.client.command(f"DROP DICTIONARY IF EXISTS {DB}.{d}")
            for t in ["map_source", "floor_dist_source", "tex_wall1_source", "tex_wall2_source",
                      "tex_floor_source", "tex_ceiling_source"]:
                self.client.command(f"DROP TABLE IF EXISTS {DB}.{t}")
        except Exception as e:
            print(f"Note: Cleanup encountered an issue: {e}")

    def execute_sql_script(self, script_path):
        if not os.path.exists(script_path):
            print(f"⚠️ Warning: SQL script '{script_path}' not found.")
            return
        with open(script_path, 'r') as f:
            content = f.read()
        for stmt in content.split(';'):
            lines, in_block = [], False
            for line in stmt.split('\n'):
                if in_block:
                    if '*/' in line:
                        in_block = False
                        line = line.split('*/', 1)[1]
                    else:
                        continue
                if not in_block:
                    if '/*' in line:
                        if '*/' in line:
                            import re
                            line = re.sub(r'/\*.*?\*/', '', line)
                        else:
                            in_block = True
                            line = line.split('/*', 1)[0]
                    if '--' in line:
                        line = line.split('--', 1)[0]
                    if line.strip():
                        lines.append(line)
            stmt = '\n'.join(lines).strip()
            if not stmt:
                continue
            print(f"💾 Executing statement from {script_path}...")
            try:
                self.client.command(stmt)
            except Exception as e:
                print(f"Error executing statement: {e}")

    def initialize_game_data(self):
        print("🎮 Initializing game data (map, floor distances)...")
        self.execute_sql_script("polling/SQL/create_source_tables.sql")
        self.execute_sql_script("polling/SQL/create_dictionaries.sql")

    def load_frame_templates(self):
        import re
        with open("polling/SQL/frame_render.sql") as f:
            content = f.read()
        chunks = re.split(r'(?m)^-- QUARTER \d+\s*$', content)
        self.frame_templates = [c.strip() for c in chunks[1:] if c.strip()]
        if len(self.frame_templates) != 4:
            raise RuntimeError(f"expected 4 frame templates, got {len(self.frame_templates)}")

    def turn_right_logic(self):
        old = self.dir_x
        self.dir_x = self.dir_x * math.cos(-ROT_SPEED) - self.dir_y * math.sin(-ROT_SPEED)
        self.dir_y = old * math.sin(-ROT_SPEED) + self.dir_y * math.cos(-ROT_SPEED)
        oldp = self.plane_x
        self.plane_x = self.plane_x * math.cos(-ROT_SPEED) - self.plane_y * math.sin(-ROT_SPEED)
        self.plane_y = oldp * math.sin(-ROT_SPEED) + self.plane_y * math.cos(-ROT_SPEED)

    def turn_left_logic(self):
        old = self.dir_x
        self.dir_x = self.dir_x * math.cos(ROT_SPEED) - self.dir_y * math.sin(ROT_SPEED)
        self.dir_y = old * math.sin(ROT_SPEED) + self.dir_y * math.cos(ROT_SPEED)
        oldp = self.plane_x
        self.plane_x = self.plane_x * math.cos(ROT_SPEED) - self.plane_y * math.sin(ROT_SPEED)
        self.plane_y = oldp * math.sin(ROT_SPEED) + self.plane_y * math.cos(ROT_SPEED)

    def process_input(self):
        moved = False
        if 'left' in self.keys_pressed or 'a' in self.keys_pressed:
            self.turn_left_logic(); moved = True
        if 'right' in self.keys_pressed or 'd' in self.keys_pressed:
            self.turn_right_logic(); moved = True
        tx, ty = self.pos_x, self.pos_y
        if 'up' in self.keys_pressed or 'w' in self.keys_pressed:
            tx += self.dir_x * MOVE_SPEED; ty += self.dir_y * MOVE_SPEED; moved = True
        if 'down' in self.keys_pressed or 's' in self.keys_pressed:
            tx -= self.dir_x * MOVE_SPEED; ty -= self.dir_y * MOVE_SPEED; moved = True
        if moved:
            self.render_and_paint(tx, ty)

    def render_and_paint(self, target_x, target_y):
        # Request/response: dispatch the four quarter renders concurrently, wait
        # for all four, then composite and paint. This is the polling equivalent
        # of the streaming version's push-based delivery.
        if self.rendering:
            return
        self.rendering = True
        try:
            self.frame_id += 1
            subs = {
                "@@frame_id@@": str(self.frame_id),
                "@@old_x@@": repr(self.pos_x), "@@old_y@@": repr(self.pos_y),
                "@@try_x@@": repr(target_x), "@@try_y@@": repr(target_y),
                "@@dir_x@@": repr(self.dir_x), "@@dir_y@@": repr(self.dir_y),
                "@@plane_x@@": repr(self.plane_x), "@@plane_y@@": repr(self.plane_y),
            }
            t0 = time.time()
            futs = [self.render_pool.submit(self._render_quarter, i, subs) for i in range(4)]
            quarters = [f.result() for f in futs]
            self.render_time = (time.time() - t0) * 1000
            self.total_render_time += self.render_time
            self.render_count += 1
            if any(q is None for q in quarters):
                return
            self._composite_and_draw(quarters)
        except Exception as e:
            print(f"Render error: {e}")
        finally:
            self.rendering = False

    def _render_quarter(self, idx, subs):
        query = self.frame_templates[idx]
        for k, v in subs.items():
            query = query.replace(k, v)
        if "@@" in query:
            raise ValueError(f"unsubstituted placeholder in quarter {idx + 1} template")
        rows = self.render_clients[idx].query(query).result_rows
        if not rows:
            return None
        _fid, px, py, image_data = rows[0]
        return (px, py, np.asarray(image_data, dtype=np.uint32))

    def _composite_and_draw(self, quarters):
        row = FRAME_W
        span = ROWS_PER_QUARTER * row
        p1 = quarters[0][2][:span]
        p2 = quarters[1][2][row:row + span]
        p3 = quarters[2][2][row:row + span]
        p4 = quarters[3][2][row:]
        raw_bytes = np.concatenate((p1, p2, p3, p4)).tobytes()
        image = Image.frombytes("RGB", (640, 480), raw_bytes, "raw", "RGBX")

        self.photo = ImageTk.PhotoImage(image)
        self.label.config(image=self.photo)

        self.pos_x, self.pos_y = quarters[0][0], quarters[0][1]

        now = time.time()
        dt = now - self.last_paint_time
        self.last_paint_time = now
        if dt > 0:
            self.paint_fps = 0.9 * self.paint_fps + 0.1 * (1.0 / dt) if self.frames_painted else 1.0 / dt
        self.frames_painted += 1
        avg = self.total_render_time / self.render_count if self.render_count else 0.0

        line1 = (f"{self.paint_fps:2.1f}fps (polling) | "
                 f"Render: {self.render_time:3.2f}ms (avg: {avg:3.2f}ms) | Frames: {self.frames_painted}")
        line2 = f"Pos: ({self.pos_x:5.2f}, {self.pos_y:5.2f}) | Theme: {self.current_theme.upper()} (Press 'T' to switch theme)"
        self.status_label.config(text=f"{line1}\n{line2}")

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
        self.root.after(16, self.update_loop)


def main():
    app = DOOMHouse()
    app.run()


if __name__ == "__main__":
    main()
