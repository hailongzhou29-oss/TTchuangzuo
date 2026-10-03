"""Double-click source launcher; reads only the configured runtime, not credentials."""
import runpy
from pathlib import Path
runpy.run_path(str(Path(__file__).resolve().parent/'tools/launch_gui.pyw'),run_name='__main__')
