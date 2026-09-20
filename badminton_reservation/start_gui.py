"""Run in the installed environment on Windows or macOS to open the local GUI."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from badminton_reservation.gui_server import main
if __name__ == '__main__': main()
