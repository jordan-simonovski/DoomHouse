import sys
import os

# Force Server Mode for verification
os.environ['USE_CHDB'] = 'false'

from src.DOOMHouse import DOOMHouse

# Mock tkinter to avoid GUI issues
import tkinter
from unittest.mock import MagicMock
tkinter.Tk = MagicMock()

try:
    app = DOOMHouse()
    # The __init__ calls initialize_game_data
    print("Initialization complete.")
except Exception as e:
    print(f"Initialization failed: {e}")
    sys.exit(1)
