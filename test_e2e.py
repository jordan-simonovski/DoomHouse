"""Headless end-to-end test: real render pipeline + streaming, no GUI.

Stubs Tkinter/ImageTk so DOOMHouse can initialise the database, run the real
SQL render pipeline, and drive the STREAM workers without a display. Verifies
that inserting player input produces a full 640x480 composited frame via the
streaming path.
"""
import sys, time
from unittest import mock

sys.modules['tkinter'] = mock.MagicMock()
sys.path.insert(0, 'src')
import DOOMHouse as G

G.ImageTk.PhotoImage = lambda img: img  # avoid needing a display

app = G.DOOMHouse()
app.running = True
app.start_game()  # pushes the first player_input -> drives the render pipeline

deadline = time.time() + 20
while time.time() < deadline:
    if all(q is not None for q in app.quarter_data):
        break
    time.sleep(0.1)

assert all(q is not None for q in app.quarter_data), \
    f"streams did not deliver all quarters: {[None if q is None else len(q) for q in app.quarter_data]}"
lens = [len(q) for q in app.quarter_data]
print("quarter lengths:", lens)

# Composite via the game's own logic and check the frame shape.
with app.frame_lock:
    quarters = list(app.quarter_data)
    pos = app.quarter_pos[0]
img = None
import PIL.Image as PImage
orig = G.Image.frombytes
captured = {}
def spy(mode, size, data, *a, **k):
    captured['size'] = size
    captured['nbytes'] = len(data)
    return orig(mode, size, data, *a, **k)
G.Image.frombytes = spy
app._composite_and_draw(quarters, pos)
G.Image.frombytes = orig

print("composited image size:", captured['size'], "bytes:", captured['nbytes'])
assert captured['size'] == (640, 480), captured['size']
assert captured['nbytes'] == 640 * 480 * 4, captured['nbytes']  # RGBX

# Now simulate movement: several inputs, confirm fresh frames keep streaming.
seen = 0
app.new_frame = False
for step in range(5):
    # wait for any in-flight render to finish so this push actually dispatches
    wb = time.time() + 5
    while app.render_busy and time.time() < wb:
        time.sleep(0.01)
    app.push_input(app.pos_x + 0.1, app.pos_y)
    t = time.time() + 5
    while time.time() < t and not app.new_frame:
        time.sleep(0.02)
    streamed = app.new_frame
    if streamed:
        seen += 1
        app.new_frame = False
    print(f"  movement frame {step+1}: streamed={streamed} pos=({app.pos_x:.2f},{app.pos_y:.2f})")

print(f"\nmovement frames streamed: {seen}/5")

# Confirm the frame table stays bounded by TTL (not one row per frame forever).
cnt = app.client.query(
    "SELECT count() FROM doomhouse.rendered_frame_post_processed_1"
).result_rows[0][0]
print("frame_post_processed_1 row count:", cnt)

ok = seen >= 5 and captured['size'] == (640, 480)
print("\nVERDICT:", "E2E streaming pipeline works ✓" if ok else "FAIL ✗")
app.running = False
sys.exit(0 if ok else 1)
