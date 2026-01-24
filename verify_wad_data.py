import clickhouse_connect
import os
from dotenv import load_dotenv

load_dotenv()

HOST = os.getenv('CLICKHOUSE_HOST', 'localhost')
PORT = int(os.getenv('CLICKHOUSE_PORT', '8123'))
USER = os.getenv('CLICKHOUSE_USER', 'default')
PASS = os.getenv('CLICKHOUSE_PASS', '')

try:
    client = clickhouse_connect.get_client(host=HOST, port=PORT, username=USER, password=PASS)
    
    print("Checking tables...")
    tables = ['wad_vertexes', 'wad_sectors', 'wad_sidedefs', 'wad_linedefs', 'wad_segs', 'wad_things', 'bsp_resolved']
    for table in tables:
        try:
            count = client.command(f"SELECT count() FROM doomhouse.{table}")
            print(f"Table {table}: {count} rows")
        except Exception as e:
            print(f"Table {table}: Error - {e}")

    print("\nChecking dictionary...")
    try:
        count = client.command("SELECT count() FROM doomhouse.dict_bsp_resolved")
        print(f"Dictionary dict_bsp_resolved: {count} rows")
    except Exception as e:
        print(f"Dictionary dict_bsp_resolved: Error - {e}")

except Exception as e:
    print(f"Connection failed: {e}")
