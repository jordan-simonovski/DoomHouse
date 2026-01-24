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
        res = client.query(sql)
        if res:
            return res.bytes().decode().strip()
        return ""
    else:
        return client.command(sql)

def main():
    client = get_client()
    
    print("🔍 Checking Texture Names...")
    
    try:
        # Check wad_texture_info
        print("\n--- wad_texture_info (First 5) ---")
        res = run_query(client, "SELECT id, name, type FROM doomhouse.wad_texture_info LIMIT 5")
        print(res)
        
        # Check wad_sectors
        print("\n--- wad_sectors (First 5) ---")
        res = run_query(client, "SELECT id, floor_tex, ceil_tex FROM doomhouse.wad_sectors LIMIT 5")
        print(res)
        
        # Check wad_sidedefs
        print("\n--- wad_sidedefs (First 5) ---")
        res = run_query(client, "SELECT id, middle, upper, lower FROM doomhouse.wad_sidedefs LIMIT 5")
        print(res)
        
        # Check for mismatches (Case Sensitivity)
        print("\n--- Checking for Case Mismatches ---")
        
        # Check Floor Textures
        sql = """
        SELECT count() 
        FROM doomhouse.wad_sectors s
        LEFT JOIN doomhouse.wad_texture_info t ON s.floor_tex = t.name
        WHERE t.id = 0 AND s.floor_tex != '' AND s.floor_tex != '-'
        """
        # Note: In ClickHouse, if join fails, t.id will be 0 (default for UInt32)
        
        # Actually, let's just see if we can find any that match case-insensitively but not case-sensitively
        sql = """
        SELECT s.floor_tex, t.name
        FROM doomhouse.wad_sectors s
        JOIN doomhouse.wad_texture_info t ON lower(s.floor_tex) = lower(t.name)
        WHERE s.floor_tex != t.name
        LIMIT 5
        """
        res = run_query(client, sql)
        if res:
            print("⚠️ Found Floor Texture Case Mismatches:")
            print(res)
        else:
            print("✅ No Floor Texture Case Mismatches found (or no matches at all).")

        # Check Wall Textures (Middle)
        sql = """
        SELECT s.middle, t.name
        FROM doomhouse.wad_sidedefs s
        JOIN doomhouse.wad_texture_info t ON lower(s.middle) = lower(t.name)
        WHERE s.middle != t.name
        LIMIT 5
        """
        res = run_query(client, sql)
        if res:
            print("⚠️ Found Wall Texture Case Mismatches:")
            print(res)
        else:
            print("✅ No Wall Texture Case Mismatches found.")

    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    main()
