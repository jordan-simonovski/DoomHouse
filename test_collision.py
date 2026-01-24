import clickhouse_connect
import os
import time
from dotenv import load_dotenv

load_dotenv()

HOST = os.getenv('CLICKHOUSE_HOST', 'localhost')
PORT = int(os.getenv('CLICKHOUSE_PORT', '8123'))
USER = os.getenv('CLICKHOUSE_USER', 'default')
PASS = os.getenv('CLICKHOUSE_PASS', '')

def test_collision():
    client = clickhouse_connect.get_client(host=HOST, port=PORT, username=USER, password=PASS)
    
    # Initial state
    old_x, old_y = 3.5, 3.5
    dir_x, dir_y = -1.0, 0.0
    plane_x, plane_y = 0.0, 0.66
    
    # Test 1: Move towards a wall (West wall is at x=1.0)
    try_x = 1.2 # Should be blocked because 1.2 - 1.0 = 0.2 < 0.3
    try_y = 3.5
    
    print(f"Testing move from ({old_x}, {old_y}) to ({try_x}, {try_y})")
    
    client.command("TRUNCATE TABLE doomhouse.player_input_raw")
    client.command(f"""
        INSERT INTO doomhouse.player_input_raw
        (frame_id, old_x, old_y, try_x, try_y, dir_x, dir_y, plane_x, plane_y, timestamp)
        VALUES (1, {old_x}, {old_y}, {try_x}, {try_y}, {dir_x}, {dir_y}, {plane_x}, {plane_y}, now())
    """)
    
    time.sleep(0.5)
    
    result = client.query("SELECT valid_x, valid_y FROM doomhouse.player_state")
    if result.result_rows:
        res_x, res_y = result.result_rows[0]
        print(f"Resulting position: ({res_x}, {res_y})")
        if res_x == old_x:
            print("✅ Collision detected and movement blocked (Correct)")
        else:
            print("❌ Collision NOT detected or movement allowed (Incorrect)")
    else:
        print("❌ No data in player_state")

    # Test 2: Move to a safe position
    try_x = 3.4
    try_y = 3.5
    print(f"\nTesting move from ({old_x}, {old_y}) to ({try_x}, {try_y})")
    client.command("TRUNCATE TABLE doomhouse.player_input_raw")
    client.command(f"""
        INSERT INTO doomhouse.player_input_raw
        (frame_id, old_x, old_y, try_x, try_y, dir_x, dir_y, plane_x, plane_y, timestamp)
        VALUES (2, {old_x}, {old_y}, {try_x}, {try_y}, {dir_x}, {dir_y}, {plane_x}, {plane_y}, now())
    """)
    time.sleep(0.5)
    result = client.query("SELECT valid_x, valid_y FROM doomhouse.player_state")
    if result.result_rows:
        res_x, res_y = result.result_rows[0]
        print(f"Resulting position: ({res_x}, {res_y})")
        if res_x == try_x:
            print("✅ Safe movement allowed (Correct)")
        else:
            print("❌ Safe movement blocked (Incorrect)")

    # Test 3: Sliding
    try_x = 3.2
    try_y = 3.6
    print(f"\nTesting sliding move from ({old_x}, {old_y}) to ({try_x}, {try_y})")
    client.command("TRUNCATE TABLE doomhouse.player_input_raw")
    client.command(f"""
        INSERT INTO doomhouse.player_input_raw
        (frame_id, old_x, old_y, try_x, try_y, dir_x, dir_y, plane_x, plane_y, timestamp)
        VALUES (3, {old_x}, {old_y}, {try_x}, {try_y}, {dir_x}, {dir_y}, {plane_x}, {plane_y}, now())
    """)
    time.sleep(0.5)
    result = client.query("SELECT valid_x, valid_y FROM doomhouse.player_state")
    if result.result_rows:
        res_x, res_y = result.result_rows[0]
        print(f"Resulting position: ({res_x}, {res_y})")
        if res_x == old_x and res_y == try_y:
            print("✅ Sliding detected (X blocked, Y allowed) (Correct)")
        else:
            print(f"❌ Sliding NOT working as expected. Got ({res_x}, {res_y})")

if __name__ == "__main__":
    test_collision()
