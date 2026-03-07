# PyInstaller entry point - uses absolute imports to avoid relative import errors
import os
from pathlib import Path
from tuitter.main import Proj101App

if __name__ == "__main__":
    pid_file = Path(".main_app_pid")
    pid_file.write_text(str(os.getpid()))
    try:
        app = Proj101App()
        app.run()
    finally:
        try:
            pid_file.unlink()
        except Exception:
            pass
