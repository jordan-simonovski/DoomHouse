import clickhouse_connect
import os
from dotenv import load_dotenv

load_dotenv()

HOST = os.getenv('CLICKHOUSE_HOST', 'localhost')
PORT = int(os.getenv('CLICKHOUSE_PORT', '8123'))
USER = os.getenv('CLICKHOUSE_USER', 'default')
PASS = os.getenv('CLICKHOUSE_PASS', '')

def init_db():
    client = clickhouse_connect.get_client(host=HOST, port=PORT, username=USER, password=PASS)
    
    client.command("CREATE DATABASE IF NOT EXISTS doomhouse")
    
    # Drop everything
    client.command("DROP VIEW IF EXISTS doomhouse.render_materialized")
    client.command("DROP VIEW IF EXISTS doomhouse.post_process_materialized")
    client.command("DROP VIEW IF EXISTS doomhouse.player_state_mv")
    
    dicts = ["dict_map_data", "dict_floor_dist", "dict_tex_wall", "dict_bsp_segs"]
    for d in dicts:
        client.command(f"DROP DICTIONARY IF EXISTS doomhouse.{d}")
        
    tables = ["map_source", "floor_dist_source", "player_input_raw", "player_state", "rendered_frame", "rendered_frame_post_processed", "bsp_source"]
    for t in tables:
        client.command(f"DROP TABLE IF EXISTS doomhouse.{t}")

    # Run scripts
    def run_script(path):
        with open(path, 'r') as f:
            content = f.read()
        # Remove comments
        import re
        content = re.sub(r'--.*', '', content)
        content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
        for stmt in content.split(';'):
            stmt = stmt.strip()
            if stmt:
                client.command(stmt)

    run_script("src/SQL/create_source_tables.sql")
    run_script("src/SQL/create_dictionaries.sql")
    run_script("src/SQL/player_input_table.sql")
    run_script("src/SQL/player_state_table.sql")
    run_script("src/SQL/rendered_frame_table.sql")
    run_script("src/SQL/rendered_frame_post_processed_table.sql")
    run_script("src/SQL/player_state.sql")
    
    # Populate BSP
    segments = [
        [1, 1.0, 1.0, 8.0, 1.0, 1.0, 0.0],
        [2, 8.0, 1.0, 8.0, 8.0, 1.0, 0.0],
        [3, 8.0, 8.0, 1.0, 8.0, 1.0, 0.0],
        [4, 1.0, 8.0, 1.0, 1.0, 1.0, 0.0],
        [5, 3.0, 3.0, 4.0, 3.0, 1.0, 0.0],
        [6, 4.0, 3.0, 4.0, 4.0, 1.0, 0.0],
        [7, 4.0, 4.0, 3.0, 4.0, 1.0, 0.0],
        [8, 3.0, 4.0, 3.0, 3.0, 1.0, 0.0]
    ]
    client.insert('doomhouse.bsp_source', segments)
    client.command("SYSTEM RELOAD DICTIONARY doomhouse.dict_bsp_segs")
    
    print("Database initialized.")

if __name__ == "__main__":
    init_db()
