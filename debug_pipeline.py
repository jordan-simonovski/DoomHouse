import chdb
import clickhouse_connect
import os
import sys
from dotenv import load_dotenv

load_dotenv()

HOST = os.getenv('CLICKHOUSE_HOST', 'localhost')
PORT = int(os.getenv('CLICKHOUSE_PORT', '8123'))
USER = os.getenv('CLICKHOUSE_USER', 'default')
PASS = os.getenv('CLICKHOUSE_PASS', '')
USE_CHDB = os.getenv('USE_CHDB', 'true').lower() == 'true'

def get_client():
    if USE_CHDB:
        print("🔗 Using chDB...")
        return chdb.session.Session()
    else:
        print(f"🔗 Connecting to ClickHouse Server at {HOST}:{PORT}...")
        return clickhouse_connect.get_client(host=HOST, port=PORT, username=USER, password=PASS)

def run_query(client, sql):
    if USE_CHDB:
        return client.query(sql)
    else:
        return client.command(sql)

def run_script(client, path):
    print(f"📜 Running {path}...")
    if not os.path.exists(path):
        print(f"⚠️ Warning: {path} not found")
        return
    with open(path, 'r') as f:
        content = f.read()
    statements = content.split(';')
    for stmt in statements:
        # Remove comments and whitespace
        lines = stmt.split('\n')
        clean_lines = [line.split('--')[0].strip() for line in lines]
        stmt = ' '.join(clean_lines).strip()
        if not stmt: continue
        try:
            run_query(client, stmt)
        except Exception as e:
            print(f"❌ Error in {path}: {e}")

def main():
    client = get_client()
    
    # 1. Setup
    print("🧹 Cleaning up...")
    try:
        run_query(client, "DROP DATABASE IF EXISTS doomhouse")
    except:
        pass
    run_query(client, "CREATE DATABASE IF NOT EXISTS doomhouse")
    
    # Create source tables first
    run_script(client, "src/SQL/create_source_tables.sql")
    
    # Populate BSP segments
    print("📐 Populating BSP segments...")
    segments = [
        [1, 1.0, 1.0, 8.0, 1.0, 1.0, 0.0],
        [2, 8.0, 1.0, 8.0, 8.0, 1.0, 0.0],
        [3, 8.0, 8.0, 1.0, 8.0, 1.0, 0.0],
        [4, 1.0, 8.0, 1.0, 1.0, 1.0, 0.0]
    ]
    values = [f"({s[0]},{s[1]},{s[2]},{s[3]},{s[4]},{s[5]},{s[6]})" for s in segments]
    run_query(client, f"INSERT INTO doomhouse.bsp_source (id, x1, y1, x2, y2, ceil, floor) VALUES {','.join(values)}")
    
    # Create dictionaries
    run_script(client, "src/SQL/create_dictionaries.sql")

    # Create dummy texture dictionaries
    print("🎨 Creating dummy texture dictionaries...")
    tex_dicts = ["dict_tex_wall", "dict_tex_floor_data", "dict_tex_ceiling_data"]
    for d in tex_dicts:
        table_name = f"{d}_table"
        run_query(client, f"CREATE TABLE doomhouse.{table_name} (id UInt32, r UInt8, g UInt8, b UInt8) ENGINE = Memory")
        run_query(client, f"INSERT INTO doomhouse.{table_name} VALUES (1, 255, 255, 255)")
        run_query(client, f"""
            CREATE DICTIONARY doomhouse.{d} (
                id UInt32, r UInt8, g UInt8, b UInt8
            )
            PRIMARY KEY id
            SOURCE(CLICKHOUSE(TABLE '{table_name}' DB 'doomhouse'))
            LIFETIME(MIN 3600 MAX 3600)
            LAYOUT(FLAT())
        """)

    scripts = [
        "src/SQL/player_input_table.sql",
        "src/SQL/player_state_table.sql",
        "src/SQL/rendered_frame_table.sql",
        "src/SQL/rendered_frame_post_processed_table.sql",
        "src/SQL/player_state.sql",
        "src/SQL/render_view.sql",
        "src/SQL/post_process_view.sql",
    ]
    
    for s in scripts:
        run_script(client, s)

    # Test MV Chaining
    print("🔗 Testing MV Chaining...")
    run_query(client, "CREATE TABLE doomhouse.test_a (id UInt32) ENGINE = Memory")
    run_query(client, "CREATE TABLE doomhouse.test_b (id UInt32) ENGINE = Memory")
    run_query(client, "CREATE TABLE doomhouse.test_c (id UInt32) ENGINE = Memory")
    run_query(client, "CREATE MATERIALIZED VIEW doomhouse.test_mv1 TO doomhouse.test_b AS SELECT id FROM doomhouse.test_a")
    run_query(client, "CREATE MATERIALIZED VIEW doomhouse.test_mv2 TO doomhouse.test_c AS SELECT id FROM doomhouse.test_b")
    run_query(client, "INSERT INTO doomhouse.test_a VALUES (1)")
    count_b = run_query(client, "SELECT count() FROM doomhouse.test_b")
    count_c = run_query(client, "SELECT count() FROM doomhouse.test_c")
    if USE_CHDB:
        print(f"   📊 Test B: {count_b.bytes().decode().strip()}, Test C: {count_c.bytes().decode().strip()}")
    else:
        print(f"   📊 Test B: {count_b}, Test C: {count_c}")

    # 2. Trigger Pipeline
    print("🚀 Inserting into player_input_raw...")
    run_query(client, "TRUNCATE TABLE doomhouse.player_input_raw")
    run_query(client, """
        INSERT INTO doomhouse.player_input_raw
        (frame_id, old_x, old_y, try_x, try_y, dir_x, dir_y, plane_x, plane_y, timestamp)
        VALUES (1, 3.5, 3.5, 3.6, 3.5, -1.0, 0.0, 0.0, 0.66, now())
    """)

    # 3. Inspect Tables
    print("🔍 Manually running render_view query...")
    try:
        with open("src/SQL/render_view.sql", "r") as f:
            sql = f.read()
        # Extract the SELECT part
        select_part = sql.split("AS", 1)[1].strip()
        if USE_CHDB:
            res = client.query(select_part)
            print(f"   ✅ Manual query returned {len(res.bytes())} bytes")
        else:
            res = client.query(select_part)
            print(f"   ✅ Manual query returned {len(res.result_rows)} rows")
    except Exception as e:
        print(f"   ❌ Manual query failed: {e}")

    tables = [
        "doomhouse.player_input_raw",
        "doomhouse.player_state",
        "doomhouse.rendered_frame",
        "doomhouse.rendered_frame_post_processed"
    ]
    
    for t in tables:
        try:
            if USE_CHDB:
                res = client.query(f"SELECT count() FROM {t}").bytes().decode().strip()
                print(f"📊 Table {t}: {res} rows")
                if int(res) > 0:
                    if t == "doomhouse.player_state":
                        content = client.query(f"SELECT * FROM {t}").bytes().decode().strip()
                        print(f"   📝 Content: {content}")
                    if "frame" in t:
                        res_data = client.query(f"SELECT length(image_data) FROM {t} LIMIT 1").bytes().decode().strip()
                        print(f"   📏 image_data length: {res_data}")
            else:
                res = client.command(f"SELECT count() FROM {t}")
                print(f"📊 Table {t}: {res} rows")
                if int(res) > 0:
                    if t == "doomhouse.player_state":
                        content = client.command(f"SELECT * FROM {t}")
                        print(f"   📝 Content: {content}")
                    if "frame" in t:
                        res_data = client.command(f"SELECT length(image_data) FROM {t} LIMIT 1")
                        print(f"   📏 image_data length: {res_data}")
        except Exception as e:
            print(f"❌ Error inspecting {t}: {e}")

if __name__ == "__main__":
    main()
