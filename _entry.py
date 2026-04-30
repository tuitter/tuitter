# PyInstaller entry point - uses absolute imports to avoid relative import errors
import os
import warnings
warnings.filterwarnings("ignore", message=".*character detection.*")
from pathlib import Path
from tuitter.main import TuitterApp, _check_version_or_exit

if __name__ == "__main__":
    _check_version_or_exit()

    pid_file = Path.home() / ".tuitter_pid"
    pid_file.write_text(str(os.getpid()))
    try:
        app = TuitterApp()
        app.run()
    finally:
        try:
            pid_file.unlink()
        except Exception:
            pass
